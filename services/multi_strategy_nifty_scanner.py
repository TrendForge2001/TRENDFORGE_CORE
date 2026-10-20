"""R72.5.2 NIFTY 100/200/500 multi-strategy scanner service."""
from __future__ import annotations

from datetime import datetime, time, timedelta
import threading
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from indicators.indicator_engine import IndicatorEngine
from providers.nse_broad_market_constituents import (
    NSEBroadMarketConstituentProvider,
    normalize_index_name,
)
from scanner.multi_strategy_engine import MultiStrategyEngine


class MultiStrategyNiftyScanner:
    """Evaluate the R72.5 strategy registry against a NIFTY universe.

    This service is scanner-only.  It intentionally has no paper-trading or
    broker-order dependency.  Long NIFTY scans are started on a daemon thread
    so the API remains responsive while Kite historical candles are fetched.
    """

    VERSION = "R72.5.2-v1"
    MARKET_TZ = ZoneInfo("Asia/Kolkata")
    MODE_CONFIG = {
        "intraday": {
            "interval": "15m",
            "default_period": "60d",
            "allowed_periods": ("30d", "45d", "60d"),
        },
        "swing": {
            "interval": "1d",
            "default_period": "2y",
            "allowed_periods": ("1y", "2y", "5y"),
        },
        "positional": {
            "interval": "1d",
            "default_period": "5y",
            "allowed_periods": ("2y", "5y"),
        },
    }

    def __init__(
        self,
        *,
        market_data: Any,
        indicator_engine: IndicatorEngine | None = None,
        strategy_engine: MultiStrategyEngine | None = None,
        universe_provider: NSEBroadMarketConstituentProvider | None = None,
    ) -> None:
        if market_data is None:
            raise ValueError("market_data is required")
        self.market_data = market_data
        self.indicators = indicator_engine or IndicatorEngine()
        self.strategies = strategy_engine or MultiStrategyEngine()
        self.universe_provider = universe_provider or NSEBroadMarketConstituentProvider()
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._status = "idle"
        self._active_request: dict[str, Any] | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._thread: threading.Thread | None = None

    @classmethod
    def _now(cls) -> datetime:
        return datetime.now(cls.MARKET_TZ)

    @staticmethod
    def _label(value: Any) -> str:
        try:
            return pd.Timestamp(value).isoformat()
        except Exception:
            return str(value)

    @classmethod
    def _as_ist(cls, value: Any) -> pd.Timestamp | None:
        try:
            stamp = pd.Timestamp(value)
        except Exception:
            return None
        if pd.isna(stamp):
            return None
        if stamp.tzinfo is None:
            try:
                return stamp.tz_localize(cls.MARKET_TZ)
            except Exception:
                return stamp
        try:
            return stamp.tz_convert(cls.MARKET_TZ)
        except Exception:
            return stamp

    @classmethod
    def _completed_bars(
        cls,
        frame: pd.DataFrame,
        *,
        interval: str,
        now: datetime | None = None,
    ) -> pd.DataFrame:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError("No historical market data returned")
        result = frame.sort_index().copy()
        current = now or cls._now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=cls.MARKET_TZ)
        else:
            current = current.astimezone(cls.MARKET_TZ)

        last_stamp = cls._as_ist(result.index[-1])
        if last_stamp is None:
            return result

        if interval == "1d":
            if last_stamp.date() == current.date() and current.time() < time(15, 30):
                result = result.iloc[:-1]
        else:
            minutes = {
                "5m": 5,
                "10m": 10,
                "15m": 15,
                "30m": 30,
                "60m": 60,
                "1h": 60,
            }.get(interval)
            if minutes is not None:
                close_at = last_stamp.to_pydatetime() + timedelta(minutes=minutes)
                if current < close_at:
                    result = result.iloc[:-1]

        if result.empty:
            raise ValueError("No completed candles available")
        return result

    @classmethod
    def _intraday_session_overrides(cls, frame: pd.DataFrame) -> pd.DataFrame:
        """Reset VWAP by trading day and use prior-session Fibonacci pivots."""
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.empty:
            return frame

        output = frame.copy()
        local = frame.index
        try:
            local = (
                local.tz_localize(cls.MARKET_TZ)
                if local.tz is None
                else local.tz_convert(cls.MARKET_TZ)
            )
        except Exception:
            pass
        sessions = pd.Series(
            [stamp.date() for stamp in local],
            index=output.index,
            name="_session",
        )

        typical = (
            output["high"].astype(float)
            + output["low"].astype(float)
            + output["close"].astype(float)
        ) / 3.0
        weighted = typical * output["volume"].astype(float)
        grouped_volume = output["volume"].astype(float).groupby(sessions).cumsum()
        grouped_weighted = weighted.groupby(sessions).cumsum()
        output["VWAP"] = grouped_weighted / grouped_volume.replace(0, float("nan"))

        daily = (
            output.assign(_session=sessions.values)
            .groupby("_session")
            .agg(
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
            )
        )
        previous = daily.shift(1)
        pivot = (previous["high"] + previous["low"] + previous["close"]) / 3.0
        spread = previous["high"] - previous["low"]
        levels = pd.DataFrame(
            {
                "FIB_PIVOT": pivot,
                "FIB_R1": pivot + 0.382 * spread,
                "FIB_R2": pivot + 0.618 * spread,
                "FIB_R3": pivot + 1.000 * spread,
                "FIB_S1": pivot - 0.382 * spread,
                "FIB_S2": pivot - 0.618 * spread,
                "FIB_S3": pivot - 1.000 * spread,
            }
        )
        for column in levels.columns:
            output[column] = sessions.map(levels[column])
        return output

    @classmethod
    def _mode_config(
        cls,
        mode: str,
        period: str | None,
    ) -> tuple[str, str, str]:
        key = str(mode or "").strip().lower()
        if key not in cls.MODE_CONFIG:
            raise ValueError("mode must be intraday, swing or positional")
        config = cls.MODE_CONFIG[key]
        resolved = str(period or config["default_period"]).strip().lower()
        if resolved not in config["allowed_periods"]:
            raise ValueError(
                f"{key} period must be one of: "
                + ", ".join(config["allowed_periods"])
            )
        return key, str(config["interval"]), resolved

    def _universe(
        self,
        name: str,
        *,
        limit: int | None,
        force_refresh: bool,
    ) -> tuple[str, list[str], dict[str, Any]]:
        normalized = normalize_index_name(name)
        payload = self.universe_provider.load(
            normalized,
            force_refresh=force_refresh,
        )
        symbols = [
            str(item.get("symbol") or "").strip().upper()
            for item in payload.get("members") or []
            if str(item.get("symbol") or "").strip()
        ]
        expected = int(payload.get("minimum_security_count") or 0)
        if expected and len(symbols) < expected:
            raise RuntimeError(
                f"{normalized} universe incomplete: {len(symbols)} < {expected}"
            )
        if limit is not None:
            value = int(limit)
            if value < 1 or value > 500:
                raise ValueError("limit must be between 1 and 500")
            symbols = symbols[:value]
        if not symbols:
            raise RuntimeError(f"{normalized} universe returned no symbols")
        return normalized, symbols, payload

    def _provider_observation(self, symbols: list[str]) -> dict[str, Any]:
        method = getattr(self.market_data, "observability_snapshot", None)
        if not callable(method):
            return {}
        try:
            payload = method(symbols)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _compact_evaluation(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "strategy_id": item.get("strategy_id"),
            "name": item.get("name"),
            "source": item.get("source"),
            "family": item.get("family"),
            "status": item.get("status"),
            "signal": item.get("signal"),
            "score": item.get("score"),
            "passed_checks": item.get("passed_checks"),
            "failed_checks": item.get("failed_checks"),
            "limitations": item.get("limitations"),
            "confirmation_only": item.get("confirmation_only"),
        }

    def scan(
        self,
        *,
        universe: str = "NIFTY 100",
        mode: str = "swing",
        source: str = "all",
        strategy_ids: list[str] | None = None,
        period: str | None = None,
        top_n: int = 20,
        limit: int | None = None,
        force_refresh_universe: bool = False,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Multi-strategy scanner is already running")
        started = now or self._now()
        mode_key, interval, resolved_period = self._mode_config(mode, period)
        run_id = str(run_id or "").strip() or f"r7252-{uuid4().hex[:12]}"
        try:
            normalized_universe, symbols, universe_payload = self._universe(
                universe,
                limit=limit,
                force_refresh=bool(force_refresh_universe),
            )
            selected_strategies = self.strategies.strategies(
                mode=mode_key,
                source=source,
                strategy_ids=strategy_ids,
            )
            strategy_names = {
                item["strategy_id"]: item.get("name")
                for item in selected_strategies
            }

            begin = getattr(self.market_data, "begin_observation", None)
            if callable(begin):
                begin()
            frames, failures = self.market_data.batch_candles_with_errors(
                symbols,
                period=resolved_period,
                interval=interval,
            )

            summary: dict[str, dict[str, Any]] = {
                item["strategy_id"]: {
                    "strategy_id": item["strategy_id"],
                    "name": item.get("name"),
                    "source": item.get("source"),
                    "evaluated": 0,
                    "buy": 0,
                    "exit": 0,
                    "confirm_buy": 0,
                    "confirm_sell": 0,
                    "neutral_or_hold": 0,
                    "review_required": 0,
                    "not_implemented": 0,
                }
                for item in selected_strategies
            }
            results: list[dict[str, Any]] = []
            full_candidates: list[dict[str, Any]] = []
            errors: list[dict[str, Any]] = []

            for symbol in symbols:
                raw = frames.get(symbol)
                if raw is None:
                    errors.append(
                        {
                            "symbol": symbol,
                            "error": failures.get(symbol, "Kite returned no candle data"),
                        }
                    )
                    continue
                try:
                    completed = self._completed_bars(
                        raw,
                        interval=interval,
                        now=started,
                    )
                    if len(completed) < 120:
                        raise ValueError("At least 120 completed candles are required")
                    frame = self.indicators.calculate(completed.copy())
                    if mode_key == "intraday":
                        frame = self._intraday_session_overrides(frame)

                    evaluation = self.strategies.evaluate(
                        frame,
                        mode=mode_key,
                        interval=interval,
                        source=source,
                        strategy_ids=strategy_ids,
                    )
                    for item in evaluation["evaluations"]:
                        row = summary[item["strategy_id"]]
                        status = str(item.get("status") or "")
                        signal = str(item.get("signal") or "")
                        if status == "evaluated":
                            row["evaluated"] += 1
                            if signal == "BUY":
                                row["buy"] += 1
                            elif signal == "EXIT":
                                row["exit"] += 1
                            elif signal == "CONFIRM_BUY":
                                row["confirm_buy"] += 1
                            elif signal == "CONFIRM_SELL":
                                row["confirm_sell"] += 1
                            else:
                                row["neutral_or_hold"] += 1
                        elif status == "review_required":
                            row["review_required"] += 1
                        else:
                            row["not_implemented"] += 1

                    compact = {
                        "symbol": symbol,
                        "bar_at": self._label(frame.index[-1]),
                        "consensus": evaluation["consensus"],
                        "consensus_score": evaluation["consensus_score"],
                        "buy_strategy_count": evaluation["buy_strategy_count"],
                        "notebook_buy_count": evaluation["notebook_buy_count"],
                        "template_buy_count": evaluation["template_buy_count"],
                        "bullish_confirmation_count": evaluation[
                            "bullish_confirmation_count"
                        ],
                        "exit_strategy_count": evaluation["exit_strategy_count"],
                        "buy_strategy_ids": evaluation["buy_strategy_ids"],
                        "confirmation_strategy_ids": evaluation[
                            "confirmation_strategy_ids"
                        ],
                        "primary_strategy_id": evaluation["primary_strategy_id"],
                        "risk": evaluation["risk"],
                    }
                    results.append(compact)
                    if evaluation["consensus"] in {"BUY", "STRONG_BUY"}:
                        full_candidates.append(
                            {
                                **compact,
                                "strategy_evaluations": [
                                    self._compact_evaluation(item)
                                    for item in evaluation["evaluations"]
                                    if item.get("signal") in {
                                        "BUY",
                                        "CONFIRM_BUY",
                                    }
                                    or item.get("status") == "review_required"
                                ],
                            }
                        )
                except Exception as exc:
                    errors.append(
                        {
                            "symbol": symbol,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

            ranked_results = sorted(
                results,
                key=lambda item: (
                    item.get("consensus") == "STRONG_BUY",
                    int(item.get("buy_strategy_count") or 0),
                    float(item.get("consensus_score") or 0.0),
                ),
                reverse=True,
            )
            ranked_candidates = sorted(
                full_candidates,
                key=lambda item: (
                    item.get("consensus") == "STRONG_BUY",
                    int(item.get("buy_strategy_count") or 0),
                    float(item.get("consensus_score") or 0.0),
                ),
                reverse=True,
            )
            top_n_value = max(1, min(100, int(top_n)))
            completed_at = self._now()
            payload = {
                "status": "completed" if not errors else "degraded",
                "version": self.VERSION,
                "engine_version": self.strategies.VERSION,
                "run_id": run_id,
                "universe": normalized_universe,
                "mode": mode_key,
                "source": source,
                "period": resolved_period,
                "interval": interval,
                "started_at_ist": started.isoformat(),
                "completed_at_ist": completed_at.isoformat(),
                "requested_symbols": len(symbols),
                "completed_symbols": len(results),
                "error_symbols": len(errors),
                "candidate_symbols": len(ranked_candidates),
                "strong_buy_symbols": sum(
                    1 for item in ranked_candidates
                    if item.get("consensus") == "STRONG_BUY"
                ),
                "strategies_requested": len(selected_strategies),
                "strategy_ids": list(strategy_names),
                "strategy_summary": list(summary.values()),
                "top_picks": ranked_candidates[:top_n_value],
                "results": ranked_results,
                "errors": errors,
                "universe_metadata": {
                    "source": universe_payload.get("source"),
                    "security_count": universe_payload.get("security_count"),
                    "fetched_at": universe_payload.get("fetched_at"),
                    "limited_to": len(symbols),
                },
                "provider_observation": self._provider_observation(symbols),
                "safety": {
                    "scanner_only": True,
                    "paper_execution_allowed": False,
                    "paper_orders_created": False,
                    "broker_orders_allowed": False,
                    "fundamentals_used": False,
                    "enrichment_used": False,
                },
            }
            with self._state_lock:
                self._last_result = payload
                self._last_error = None
            return payload
        except Exception as exc:
            with self._state_lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._run_lock.release()

    def trigger(self, **kwargs: Any) -> dict[str, Any]:
        # Fail fast before starting the worker thread.  This validation is
        # intentionally network-free; constituent retrieval happens inside
        # the background scan.
        mode = str(kwargs.get("mode") or "swing").strip().lower()
        source = str(kwargs.get("source") or "all").strip().lower()
        period = kwargs.get("period")
        self._mode_config(mode, period)
        normalize_index_name(str(kwargs.get("universe") or "NIFTY 100"))
        self.strategies.strategies(
            mode=mode,
            source=source,
            strategy_ids=kwargs.get("strategy_ids"),
        )
        limit = kwargs.get("limit")
        if limit is not None and not 1 <= int(limit) <= 500:
            raise ValueError("limit must be between 1 and 500")
        top_n = int(kwargs.get("top_n") or 20)
        if not 1 <= top_n <= 100:
            raise ValueError("top_n must be between 1 and 100")

        if self._run_lock.locked():
            return {
                "status": "busy",
                "version": self.VERSION,
                "active_request": self._active_request,
            }
        run_id = str(kwargs.pop("run_id", "") or "").strip() or f"r7252-{uuid4().hex[:12]}"
        request = {**kwargs, "run_id": run_id}
        with self._state_lock:
            self._status = "running"
            self._active_request = {
                key: value
                for key, value in request.items()
                if key != "now"
            }
            self._last_error = None

        def _work() -> None:
            try:
                result = self.scan(**request)
                with self._state_lock:
                    self._last_result = result
                    self._status = "completed"
            except Exception as exc:
                with self._state_lock:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    self._status = "failed"
            finally:
                with self._state_lock:
                    self._active_request = None

        thread = threading.Thread(
            target=_work,
            name=f"trendforge-r7252-{run_id}",
            daemon=True,
        )
        self._thread = thread
        thread.start()
        return {
            "status": "started",
            "version": self.VERSION,
            "run_id": run_id,
            "request": {
                key: value
                for key, value in request.items()
                if key != "now"
            },
            "safety": {
                "paper_execution_allowed": False,
                "broker_orders_allowed": False,
            },
        }

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            result = self._last_result
            return {
                "status": self._status,
                "version": self.VERSION,
                "busy": self._run_lock.locked(),
                "active_request": dict(self._active_request or {}),
                "last_error": self._last_error,
                "last_result": result,
                "safety": {
                    "scanner_only": True,
                    "paper_execution_allowed": False,
                    "broker_orders_allowed": False,
                    "fundamentals_used": False,
                },
            }

    def readiness(self) -> dict[str, Any]:
        market = (
            self.market_data.health()
            if callable(getattr(self.market_data, "health", None))
            else {"status": "unknown"}
        )
        universe = (
            self.universe_provider.health()
            if callable(getattr(self.universe_provider, "health", None))
            else {"status": "unknown"}
        )
        return {
            "status": "ready",
            "version": self.VERSION,
            "data_policy": "kite_only",
            "universes": ["NIFTY 100", "NIFTY 200", "NIFTY 500"],
            "modes": {
                key: {
                    "interval": value["interval"],
                    "default_period": value["default_period"],
                    "allowed_periods": list(value["allowed_periods"]),
                }
                for key, value in self.MODE_CONFIG.items()
            },
            "strategy_engine": self.strategies.readiness(),
            "indicator_engine": (
                self.indicators.health()
                if callable(getattr(self.indicators, "health", None))
                else {"status": "unknown"}
            ),
            "market_data": market,
            "universe_provider": universe,
            "execution": {
                "automatic_schedule": False,
                "paper_execution_allowed": False,
                "paper_orders_created": False,
                "broker_orders_allowed": False,
            },
            "fundamentals_used": False,
            "enrichment_used": False,
        }


__all__ = ["MultiStrategyNiftyScanner"]
