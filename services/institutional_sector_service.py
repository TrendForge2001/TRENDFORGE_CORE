"""Canonical Big Shark and NIFTY 500 sector-strength dashboard service."""
from __future__ import annotations

import math
import threading
from collections import defaultdict
from typing import Any

import pandas as pd

from database.repositories.institutional_sector_repository import (
    InstitutionalSectorRepository,
)
from engines.big_shark_engine import BigSharkEngine
from engines.sector_engine import SectorEngine


class InstitutionalSectorService:
    UNIVERSE = "NIFTY 500"
    SECTOR_KEY = "NIFTY 500"

    def __init__(
        self,
        *,
        institutional_provider: Any,
        market_data: Any,
        universe: Any,
        repository: InstitutionalSectorRepository | None = None,
    ) -> None:
        if institutional_provider is None:
            raise ValueError("institutional_provider is required")
        if market_data is None:
            raise ValueError("market_data is required")
        if universe is None:
            raise ValueError("universe is required")

        self.institutional_provider = institutional_provider
        self.market_data = market_data
        self.universe = universe
        self._owns_repository = repository is None
        self.repository = repository or InstitutionalSectorRepository()
        self.big_shark_engine = BigSharkEngine()
        self.sector_engine = SectorEngine()
        self._institutional_lock = threading.Lock()
        self._sector_lock = threading.Lock()

    @staticmethod
    def _symbol(value: Any) -> str:
        symbol = str(value or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if len(symbol) > 30:
            raise ValueError("symbol must be 30 characters or fewer")
        return symbol

    @classmethod
    def _symbols(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values or []:
            symbol = cls._symbol(raw)
            if symbol not in seen:
                seen.add(symbol)
                result.append(symbol)
        if not result:
            raise ValueError("at least one symbol is required")
        if len(result) > 25:
            raise ValueError(
                "at most 25 institutional symbols can be refreshed at once"
            )
        return result

    @staticmethod
    def _sample(members: list[Any], limit: int) -> list[Any]:
        count = len(members)
        requested = max(1, min(int(limit), count))
        if requested >= count:
            return list(members)
        if requested == 1:
            return [members[count // 2]]
        indexes = [
            round(position * (count - 1) / (requested - 1))
            for position in range(requested)
        ]
        return [members[index] for index in indexes]

    @staticmethod
    def _finite(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        return number

    @staticmethod
    def _return(close: pd.Series, bars: int) -> float | None:
        series = pd.to_numeric(close, errors="coerce").dropna()
        if len(series) <= bars:
            return None
        latest = float(series.iloc[-1])
        base = float(series.iloc[-1 - bars])
        if base == 0:
            return None
        return (latest / base - 1.0) * 100.0

    @staticmethod
    def _mean(values: list[float | None]) -> float | None:
        cleaned = [
            float(value)
            for value in values
            if value is not None and math.isfinite(float(value))
        ]
        if not cleaned:
            return None
        return sum(cleaned) / len(cleaned)

    def readiness(self) -> dict[str, Any]:
        provider_health = {}
        health = getattr(self.institutional_provider, "health", None)
        if callable(health):
            try:
                value = health()
                if isinstance(value, dict):
                    provider_health = value
            except Exception as exc:
                provider_health = {
                    "status": "degraded",
                    "error": str(exc),
                }

        return {
            "status": "ready",
            "institutional_engine": self.big_shark_engine.NAME,
            "sector_engine": self.sector_engine.NAME,
            "institutional_provider": type(
                self.institutional_provider
            ).__name__,
            "institutional_provider_health": provider_health,
            "persisted_institutional_symbols": self.repository.count(
                kind="institutional"
            ),
            "sector_snapshot_available": (
                self.repository.count(kind="sector_strength") > 0
            ),
            "institutional_methodology": (
                "source_backed_big_shark_engine"
            ),
            "sector_methodology": (
                "nifty500_sample_aggregate_canonical_sector_engine"
            ),
            "trade_signal": False,
        }

    def refresh_institutional(
        self,
        *,
        symbols: list[str],
    ) -> dict[str, Any]:
        resolved = self._symbols(symbols)
        if not self._institutional_lock.acquire(blocking=False):
            raise RuntimeError(
                "Institutional refresh is already running"
            )
        try:
            return self._refresh_institutional_locked(resolved)
        finally:
            self._institutional_lock.release()

    def _refresh_institutional_locked(
        self,
        symbols: list[str],
    ) -> dict[str, Any]:
        completed: list[str] = []
        failures: dict[str, str] = {}
        rows: list[dict[str, Any]] = []

        for symbol in symbols:
            try:
                evidence = self.institutional_provider.get(
                    symbol,
                    payload={"symbol": symbol},
                )
                evidence = (
                    dict(evidence)
                    if isinstance(evidence, dict)
                    else {}
                )
                engine_payload = {
                    "symbol": symbol,
                    **{
                        key: value
                        for key, value in evidence.items()
                        if key != "_meta"
                    },
                }
                result = self.big_shark_engine.evaluate(
                    engine_payload
                )
                metrics = dict(result.metrics or {})
                payload = {
                    "status": (
                        "ready"
                        if metrics.get("data_quality")
                        else "degraded"
                    ),
                    "symbol": symbol,
                    "score": float(result.score),
                    "confidence": float(result.confidence),
                    "grade": result.grade,
                    "passed": bool(result.passed),
                    "institutional_bias": metrics.get(
                        "institutional_bias"
                    ),
                    "data_quality": bool(
                        metrics.get("data_quality")
                    ),
                    "hard_block": bool(
                        metrics.get("hard_block")
                    ),
                    "ownership": metrics.get("ownership") or {},
                    "holding_changes": metrics.get(
                        "holding_changes"
                    ) or {},
                    "deals": metrics.get("deals") or [],
                    "promoter": metrics.get("promoter") or {},
                    "conviction": metrics.get("conviction") or {},
                    "reasons": list(result.reasons or []),
                    "warnings": list(result.warnings or []),
                    "provider_evidence": evidence.get(
                        "_meta"
                    ) or {},
                    "methodology": (
                        "source_backed_big_shark_engine"
                    ),
                    "trade_signal": False,
                }
                saved = self.repository.save(
                    "institutional",
                    symbol,
                    payload,
                    universe="NSE/BSE",
                    sample_size=1,
                )
                payload["snapshot_updated_at"] = saved.get(
                    "created_at"
                )
                completed.append(symbol)
                rows.append(payload)
            except Exception as exc:
                failures[symbol] = str(exc)

        return {
            "status": (
                "ready"
                if completed and not failures
                else "degraded"
                if completed
                else "failed"
            ),
            "requested_symbols": len(symbols),
            "completed_symbols": len(completed),
            "failed_symbols": len(failures),
            "symbols": completed,
            "failures": failures,
            "snapshots": rows,
        }

    def institutional(
        self,
        symbol: str,
    ) -> dict[str, Any]:
        normalized = self._symbol(symbol)
        record = self.repository.get(
            "institutional",
            normalized,
        )
        if record is None:
            return {
                "status": "not_available",
                "symbol": normalized,
                "message": (
                    "No persisted institutional snapshot. "
                    "Run an institutional refresh first."
                ),
            }
        payload = dict(record.get("payload") or {})
        return {
            **payload,
            "symbol": normalized,
            "snapshot_updated_at": record.get("created_at"),
        }

    def institutional_latest(
        self,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        records = self.repository.list(
            kind="institutional",
            limit=limit,
        )
        rows: list[dict[str, Any]] = []
        for record in records:
            payload = dict(record.get("payload") or {})
            rows.append(
                {
                    "symbol": payload.get(
                        "symbol",
                        record.get("snapshot_key"),
                    ),
                    "status": payload.get("status"),
                    "score": payload.get("score"),
                    "confidence": payload.get("confidence"),
                    "grade": payload.get("grade"),
                    "institutional_bias": payload.get(
                        "institutional_bias"
                    ),
                    "data_quality": payload.get("data_quality"),
                    "hard_block": payload.get("hard_block"),
                    "snapshot_updated_at": record.get(
                        "created_at"
                    ),
                }
            )
        rows.sort(
            key=lambda row: (
                float(row.get("score") or 0.0),
                float(row.get("confidence") or 0.0),
            ),
            reverse=True,
        )
        return {
            "status": "ready",
            "returned": len(rows),
            "snapshots": rows,
        }

    def _members(
        self,
        *,
        limit: int,
        refresh_universe: bool,
    ) -> list[Any]:
        loader = getattr(self.universe, "ensure_loaded", None)
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

    def refresh_sector_strength(
        self,
        *,
        limit: int = 100,
        period: str = "1y",
        interval: str = "1d",
        refresh_universe: bool = False,
    ) -> dict[str, Any]:
        if period not in {"1y", "2y"}:
            raise ValueError("period must be 1y or 2y")
        if interval != "1d":
            raise ValueError("interval must be 1d")
        requested_limit = max(25, min(int(limit), 500))

        if not self._sector_lock.acquire(blocking=False):
            raise RuntimeError(
                "Sector-strength refresh is already running"
            )
        try:
            return self._refresh_sector_strength_locked(
                limit=requested_limit,
                period=period,
                interval=interval,
                refresh_universe=refresh_universe,
            )
        finally:
            self._sector_lock.release()

    def _refresh_sector_strength_locked(
        self,
        *,
        limit: int,
        period: str,
        interval: str,
        refresh_universe: bool,
    ) -> dict[str, Any]:
        members = self._members(
            limit=limit,
            refresh_universe=refresh_universe,
        )
        symbols = [
            self._symbol(getattr(member, "symbol", ""))
            for member in members
        ]
        sectors = {
            self._symbol(getattr(member, "symbol", "")): (
                str(
                    getattr(member, "sector", "")
                    or "Unclassified"
                ).strip()
                or "Unclassified"
            )
            for member in members
        }

        begin = getattr(self.market_data, "begin_observation", None)
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
        analysis_failures: dict[str, str] = {}
        observations: list[dict[str, Any]] = []

        for symbol in symbols:
            frame = frames.get(symbol)
            if frame is None or frame.empty:
                if symbol not in provider_failures:
                    analysis_failures[symbol] = "no_market_data"
                continue
            if len(frame) < 64:
                analysis_failures[symbol] = (
                    f"insufficient_history:{len(frame)}"
                )
                continue

            close = pd.to_numeric(
                frame["close"],
                errors="coerce",
            )
            volume = pd.to_numeric(
                frame["volume"],
                errors="coerce",
            )
            if close.dropna().shape[0] < 64:
                analysis_failures[symbol] = (
                    "insufficient_valid_close_history"
                )
                continue

            change_1d = self._return(close, 1)
            change_1w = self._return(close, 5)
            change_1m = self._return(close, 21)
            change_3m = self._return(close, 63)

            valid_volume = volume.dropna()
            volume_ratio = None
            if len(valid_volume) >= 20:
                average_volume = float(
                    valid_volume.tail(20).mean()
                )
                if average_volume > 0:
                    volume_ratio = (
                        float(valid_volume.iloc[-1])
                        / average_volume
                    )

            observations.append(
                {
                    "symbol": symbol,
                    "sector": sectors[symbol],
                    "change_1d": change_1d,
                    "change_1w": change_1w,
                    "change_1m": change_1m,
                    "change_3m": change_3m,
                    "volume_ratio": volume_ratio,
                }
            )

        if len(observations) < 5:
            raise RuntimeError(
                "Sector-strength refresh produced fewer than 5 usable symbols"
            )

        market_components = {
            field: self._mean(
                [row.get(field) for row in observations]
            )
            for field in (
                "change_1d",
                "change_1w",
                "change_1m",
                "change_3m",
            )
        }
        market_return = sum(
            float(market_components[field] or 0.0) * weight
            for field, weight in (
                ("change_1d", 0.15),
                ("change_1w", 0.30),
                ("change_1m", 0.30),
                ("change_3m", 0.25),
            )
        )

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in observations:
            grouped[str(row["sector"])].append(row)

        raw_snapshots: list[dict[str, Any]] = []
        for sector, rows in grouped.items():
            one_day = [
                float(row["change_1d"])
                for row in rows
                if row.get("change_1d") is not None
            ]
            advancing = sum(
                1 for value in one_day if value > 0
            )
            declining = sum(
                1 for value in one_day if value < 0
            )
            month_values = [
                float(row["change_1m"])
                for row in rows
                if row.get("change_1m") is not None
            ]
            leadership = (
                sum(1 for value in month_values if value > 0)
                * 100.0
                / len(month_values)
                if month_values
                else None
            )

            raw_snapshots.append(
                {
                    "sector": sector,
                    "constituents": len(rows),
                    "change_1d": self._mean(
                        [row.get("change_1d") for row in rows]
                    ),
                    "change_1w": self._mean(
                        [row.get("change_1w") for row in rows]
                    ),
                    "change_1m": self._mean(
                        [row.get("change_1m") for row in rows]
                    ),
                    "change_3m": self._mean(
                        [row.get("change_3m") for row in rows]
                    ),
                    "volume_ratio": self._mean(
                        [row.get("volume_ratio") for row in rows]
                    ),
                    "advancing": advancing,
                    "declining": declining,
                    "leadership_score": leadership,
                    "market_return": market_return,
                    "fii_flow": None,
                    "dii_flow": None,
                }
            )

        ranked: list[dict[str, Any]] = []
        for snapshot in raw_snapshots:
            sector = str(snapshot["sector"])
            result = self.sector_engine.evaluate(
                {
                    "symbol": f"SECTOR:{sector}",
                    "sector_name": sector,
                    "sector_snapshot": snapshot,
                }
            )
            metrics = dict(result.metrics or {})
            normalized = dict(
                metrics.get("snapshot") or {}
            )
            ranked.append(
                {
                    "sector": sector,
                    "score": float(result.score),
                    "confidence": float(result.confidence),
                    "grade": result.grade,
                    "passed": bool(result.passed),
                    "trend": metrics.get("trend"),
                    "bias": metrics.get("bias"),
                    "sector_strength": metrics.get(
                        "sector_strength"
                    ),
                    "components": metrics.get("components") or {},
                    "constituents": snapshot["constituents"],
                    "change_1d": normalized.get("change_1d"),
                    "change_1w": normalized.get("change_1w"),
                    "change_1m": normalized.get("change_1m"),
                    "change_3m": normalized.get("change_3m"),
                    "volume_ratio": normalized.get(
                        "volume_ratio"
                    ),
                    "breadth": (
                        float(snapshot["advancing"])
                        / max(1.0, float(snapshot["declining"]))
                    ),
                    "advancing": snapshot["advancing"],
                    "declining": snapshot["declining"],
                    "leadership_score": normalized.get(
                        "leadership_score"
                    ),
                    "market_return": market_return,
                    "institutional_sector_flow_available": False,
                    "reasons": list(result.reasons or []),
                    "warnings": list(result.warnings or []),
                }
            )

        ranked.sort(
            key=lambda row: (
                float(row["score"]),
                float(row["confidence"]),
            ),
            reverse=True,
        )
        for rank, row in enumerate(ranked, start=1):
            row["rank"] = rank

        failures = {
            **provider_failures,
            **analysis_failures,
        }
        coverage_pct = round(
            len(observations) * 100.0 / len(symbols),
            2,
        )

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

        payload = {
            "status": (
                "ready"
                if coverage_pct >= 80.0
                else "degraded"
            ),
            "scope": "nifty500_sample",
            "universe": self.UNIVERSE,
            "requested_symbols": len(symbols),
            "analyzed_symbols": len(observations),
            "failed_symbols": len(failures),
            "coverage_pct": coverage_pct,
            "sample_symbols": symbols,
            "market_return_composite_pct": round(
                market_return,
                4,
            ),
            "sector_count": len(ranked),
            "sectors": ranked,
            "failures": failures,
            "provider_observation": provider_observation,
            "methodology": (
                "nifty500_sample_aggregate_canonical_sector_engine"
            ),
            "institutional_sector_flow_available": False,
            "trade_signal": False,
        }
        saved = self.repository.save(
            "sector_strength",
            self.SECTOR_KEY,
            payload,
            universe=self.UNIVERSE,
            sample_size=len(observations),
        )
        return {
            **payload,
            "snapshot_updated_at": saved.get("created_at"),
        }

    def sector_strength(self) -> dict[str, Any]:
        record = self.repository.get(
            "sector_strength",
            self.SECTOR_KEY,
        )
        if record is None:
            return {
                "status": "not_available",
                "universe": self.UNIVERSE,
                "message": (
                    "No persisted sector-strength snapshot. "
                    "Run a sector-strength refresh first."
                ),
            }
        payload = dict(record.get("payload") or {})
        return {
            **payload,
            "snapshot_updated_at": record.get("created_at"),
            "snapshot_sample_size": record.get(
                "sample_size"
            ),
        }

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()


__all__ = ["InstitutionalSectorService"]
