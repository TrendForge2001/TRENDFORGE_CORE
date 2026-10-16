"""NIFTY 500 market breadth and regime snapshot service."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from database.repositories.market_context_repository import (
    MarketContextRepository,
)
from engines.breadth_engine import BreadthEngine
from engines.canonical_market_regime_engine import (
    CanonicalMarketRegimeEngine,
)
from indicators.indicator_engine import IndicatorEngine
from scanner.market_breadth import BreadthStock, MarketBreadth


class MarketContextService:
    """Refresh and persist breadth/regime views from canonical market data."""

    UNIVERSE = "NIFTY 500"

    def __init__(
        self,
        *,
        market_data: Any,
        universe: Any,
        repository: MarketContextRepository | None = None,
    ) -> None:
        if market_data is None:
            raise ValueError("market_data is required")
        if universe is None:
            raise ValueError("universe is required")
        self.market_data = market_data
        self.universe = universe
        self._owns_repository = repository is None
        self.repository = repository or MarketContextRepository()
        self.indicators = IndicatorEngine()
        self.breadth = MarketBreadth()
        self.breadth_engine = BreadthEngine()
        self.regime_engine = CanonicalMarketRegimeEngine()

    @staticmethod
    def _sample(
        members: list[Any],
        limit: int,
    ) -> list[Any]:
        count = len(members)
        requested = max(1, min(int(limit), count))
        if requested >= count:
            return list(members)
        if requested == 1:
            return [members[count // 2]]

        indexes = [
            round(
                position
                * (count - 1)
                / (requested - 1)
            )
            for position in range(requested)
        ]
        return [members[index] for index in indexes]

    @staticmethod
    def _finite(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if pd.isna(number):
            return None
        return number

    @staticmethod
    def _normalized_composite(
        frames: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        normalized: dict[str, pd.DataFrame] = {}
        for symbol, frame in frames.items():
            if frame is None or frame.empty:
                continue
            base = float(frame["close"].iloc[0])
            if base <= 0:
                continue

            view = frame.loc[
                :,
                ["open", "high", "low", "close", "volume"],
            ].copy()
            for field in ("open", "high", "low", "close"):
                view[field] = (
                    pd.to_numeric(
                        view[field],
                        errors="coerce",
                    )
                    / base
                    * 100.0
                )
            view["volume"] = pd.to_numeric(
                view["volume"],
                errors="coerce",
            )
            normalized[symbol] = view

        if not normalized:
            raise ValueError(
                "No market data available for market composite"
            )

        combined = pd.concat(
            normalized,
            axis=1,
        )
        composite = pd.DataFrame(index=combined.index)
        for field in ("open", "high", "low", "close"):
            composite[field] = combined.xs(
                field,
                level=1,
                axis=1,
            ).mean(axis=1, skipna=True)
        composite["volume"] = combined.xs(
            "volume",
            level=1,
            axis=1,
        ).sum(axis=1, skipna=True)

        composite = composite.dropna(
            subset=["open", "high", "low", "close"],
        ).sort_index()
        if len(composite) < 50:
            raise ValueError(
                "Market composite requires at least 50 aligned candles"
            )
        return composite

    def _members(
        self,
        *,
        limit: int,
        refresh_universe: bool,
    ) -> list[Any]:
        loader = getattr(
            self.universe,
            "ensure_loaded",
            None,
        )
        if not callable(loader):
            raise RuntimeError(
                "Configured universe does not expose ensure_loaded()"
            )
        members = list(
            loader(refresh=bool(refresh_universe))
        )
        if not members:
            raise RuntimeError(
                "NIFTY 500 universe returned no members"
            )
        return self._sample(members, limit)

    def refresh(
        self,
        *,
        limit: int = 100,
        period: str = "1y",
        interval: str = "1d",
        refresh_universe: bool = False,
    ) -> dict[str, Any]:
        requested_limit = max(25, min(int(limit), 500))
        members = self._members(
            limit=requested_limit,
            refresh_universe=refresh_universe,
        )
        symbols = [
            str(getattr(member, "symbol", "")).strip().upper()
            for member in members
        ]
        sector_by_symbol = {
            str(getattr(member, "symbol", "")).strip().upper():
            (
                str(
                    getattr(member, "sector", "")
                    or "Unclassified"
                ).strip()
                or "Unclassified"
            )
            for member in members
        }

        begin = getattr(
            self.market_data,
            "begin_observation",
            None,
        )
        if callable(begin):
            begin()

        batch = getattr(
            self.market_data,
            "batch_candles_with_errors",
            None,
        )
        if not callable(batch):
            raise RuntimeError(
                "Market data adapter does not support batch candles"
            )

        frames, provider_failures = batch(
            symbols,
            period=period,
            interval=interval,
        )
        provider_failures = dict(provider_failures or {})
        accepted: dict[str, pd.DataFrame] = {}
        breadth_stocks: list[BreadthStock] = []
        analysis_failures: dict[str, str] = {}

        for symbol in symbols:
            frame = frames.get(symbol)
            if frame is None or frame.empty:
                if symbol not in provider_failures:
                    analysis_failures[symbol] = "no_market_data"
                continue
            if len(frame) < 200:
                analysis_failures[symbol] = (
                    f"insufficient_history:{len(frame)}"
                )
                continue

            data = frame.copy()
            close = pd.to_numeric(
                data["close"],
                errors="coerce",
            )
            volume = pd.to_numeric(
                data["volume"],
                errors="coerce",
            )
            if close.dropna().shape[0] < 200:
                analysis_failures[symbol] = (
                    "insufficient_valid_close_history"
                )
                continue

            latest = float(close.iloc[-1])
            previous = float(close.iloc[-2])
            if previous == 0:
                analysis_failures[symbol] = (
                    "previous_close_zero"
                )
                continue

            ema20 = float(
                close.ewm(
                    span=20,
                    adjust=False,
                ).mean().iloc[-1]
            )
            ema50 = float(
                close.ewm(
                    span=50,
                    adjust=False,
                ).mean().iloc[-1]
            )
            ema200 = float(
                close.ewm(
                    span=200,
                    adjust=False,
                ).mean().iloc[-1]
            )
            window = close.tail(min(252, len(close)))
            change_pct = (
                (latest - previous)
                * 100.0
                / previous
            )

            breadth_stocks.append(
                BreadthStock(
                    symbol=symbol,
                    sector=sector_by_symbol.get(
                        symbol,
                        "Unclassified",
                    ),
                    close=latest,
                    ema20=ema20,
                    ema50=ema50,
                    ema200=ema200,
                    is_new_high=bool(
                        latest >= float(window.max())
                    ),
                    is_new_low=bool(
                        latest <= float(window.min())
                    ),
                    change_percent=float(change_pct),
                )
            )
            accepted[symbol] = data

        success_count = len(breadth_stocks)
        if success_count < 5:
            raise RuntimeError(
                "Market context refresh produced fewer than 5 usable symbols"
            )

        breadth_result = self.breadth.calculate(
            breadth_stocks
        )
        breadth_engine_result = self.breadth_engine.evaluate(
            {
                "advances": breadth_result.advances,
                "declines": breadth_result.declines,
                "unchanged": breadth_result.unchanged,
                "total_stocks": success_count,
                "new_highs": breadth_result.new_highs,
                "new_lows": breadth_result.new_lows,
            }
        )

        all_failures = {
            **provider_failures,
            **analysis_failures,
        }
        coverage_pct = round(
            success_count * 100.0 / len(symbols),
            2,
        )
        sector_strength = [
            {
                "sector": sector,
                "average_change_pct": float(value),
            }
            for sector, value in (
                breadth_result.sector_strength or {}
            ).items()
        ]

        provider_observation = {}
        observation = getattr(
            self.market_data,
            "observability_snapshot",
            None,
        )
        if callable(observation):
            try:
                value = observation(symbols)
                if isinstance(value, dict):
                    provider_observation = value
            except Exception:
                provider_observation = {}

        breadth_payload = {
            "status": (
                "ready"
                if coverage_pct >= 80.0
                else "degraded"
            ),
            "scope": "nifty500_sample",
            "universe": self.UNIVERSE,
            "requested_symbols": len(symbols),
            "analyzed_symbols": success_count,
            "failed_symbols": len(all_failures),
            "coverage_pct": coverage_pct,
            "sample_symbols": symbols,
            "advances": breadth_result.advances,
            "declines": breadth_result.declines,
            "unchanged": breadth_result.unchanged,
            "advance_decline_ratio": (
                breadth_result.advance_decline_ratio
            ),
            "advance_decline_line": (
                breadth_result.advance_decline_line
            ),
            "new_highs": breadth_result.new_highs,
            "new_lows": breadth_result.new_lows,
            "above_ema20_pct": breadth_result.above_ema20,
            "above_ema50_pct": breadth_result.above_ema50,
            "above_ema200_pct": breadth_result.above_ema200,
            "breadth_score": breadth_result.breadth_score,
            "direction": (
                breadth_engine_result.metrics or {}
            ).get("direction"),
            "engine_score": float(
                breadth_engine_result.score
            ),
            "confidence": float(
                breadth_engine_result.confidence
            ),
            "data_quality": (
                breadth_engine_result.metrics or {}
            ).get("data_quality"),
            "sector_strength": sector_strength,
            "failures": all_failures,
            "provider_observation": provider_observation,
        }

        composite = self._normalized_composite(
            accepted
        )
        enriched = self.indicators.calculate(
            composite
        )
        regime_result = self.regime_engine.evaluate(
            {
                "df": enriched,
                "breadth": {
                    "advancing": breadth_result.advances,
                    "declining": breadth_result.declines,
                },
            }
        )
        regime_metrics = dict(
            regime_result.metrics or {}
        )
        regime_payload = {
            "status": (
                "ready"
                if regime_metrics.get("regime")
                else "degraded"
            ),
            "scope": "nifty500_equal_weight_sample_composite",
            "universe": self.UNIVERSE,
            "requested_symbols": len(symbols),
            "analyzed_symbols": success_count,
            "coverage_pct": coverage_pct,
            "regime": regime_metrics.get("regime"),
            "direction": regime_metrics.get("direction"),
            "score": float(regime_result.score),
            "confidence": float(
                regime_result.confidence
            ),
            "grade": regime_result.grade,
            "passed": bool(regime_result.passed),
            "trend_score": self._finite(
                regime_metrics.get("trend_score")
            ),
            "momentum_score": self._finite(
                regime_metrics.get("momentum_score")
            ),
            "volatility_score": self._finite(
                regime_metrics.get("volatility_score")
            ),
            "participation_score": self._finite(
                regime_metrics.get(
                    "participation_score"
                )
            ),
            "breadth_component_score": self._finite(
                regime_metrics.get("breadth_score")
            ),
            "close": self._finite(
                regime_metrics.get("close")
            ),
            "ema20": self._finite(
                regime_metrics.get("EMA_20")
            ),
            "ema50": self._finite(
                regime_metrics.get("EMA_50")
            ),
            "ema200": self._finite(
                regime_metrics.get("EMA_200")
            ),
            "rsi": self._finite(
                regime_metrics.get("RSI")
            ),
            "adx": self._finite(
                regime_metrics.get("ADX")
            ),
            "atr_percent": self._finite(
                regime_metrics.get("ATR_PERCENT")
            ),
            "rvol": self._finite(
                regime_metrics.get("RVOL")
            ),
            "reasons": list(
                regime_result.reasons or []
            ),
            "warnings": list(
                regime_result.warnings or []
            ),
            "methodology": (
                "equal_weight_normalized_sample_composite"
            ),
        }

        self.repository.save(
            "breadth",
            breadth_payload,
            universe=self.UNIVERSE,
            sample_size=success_count,
        )
        self.repository.save(
            "regime",
            regime_payload,
            universe=self.UNIVERSE,
            sample_size=success_count,
        )

        return {
            "status": (
                "ready"
                if (
                    breadth_payload["status"] == "ready"
                    and regime_payload["status"] == "ready"
                )
                else "degraded"
            ),
            "universe": self.UNIVERSE,
            "requested_symbols": len(symbols),
            "analyzed_symbols": success_count,
            "coverage_pct": coverage_pct,
            "breadth": breadth_payload,
            "regime": regime_payload,
        }

    def snapshot(
        self,
        kind: str,
    ) -> dict[str, Any]:
        key = str(kind or "").strip().lower()
        if key not in {"breadth", "regime"}:
            raise ValueError(
                "market context kind must be breadth or regime"
            )
        record = self.repository.get(key)
        if record is None:
            return {
                "status": "not_available",
                "kind": key,
                "universe": self.UNIVERSE,
                "message": (
                    "No persisted market context snapshot. "
                    "Run a market context refresh first."
                ),
            }
        payload = record.get("payload")
        payload = (
            dict(payload)
            if isinstance(payload, dict)
            else {}
        )
        return {
            **payload,
            "kind": key,
            "snapshot_updated_at": record.get(
                "created_at"
            ),
            "snapshot_sample_size": record.get(
                "sample_size"
            ),
        }

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()


__all__ = ["MarketContextService"]
