"""Technical-only scanner, paper-trading handoff and backtest service.

R71.2 keeps fundamentals/enrichment outside this path. Historical OHLCV is
expected from a Kite-only market-data adapter. Technical signals use the
canonical IndicatorEngine and the same profile definitions for paper scans and
historical backtests.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.technical_realistic_engine import (
    TechnicalRealisticBacktestEngine,
    TechnicalRealisticConfig,
)
from database.repositories.backtest_results import BacktestResultsRepository
from indicators.indicator_engine import IndicatorEngine
from scanner.strategy_registry import registry_readiness
from scanner.technical_strategy import (
    entry_decision,
    exit_decision,
    latest_signal,
    strategy_profile,
)

logger = logging.getLogger(__name__)


class TechnicalTradingValidationError(ValueError):
    """A fixed, local technical-request or candle validation message."""


class TechnicalTradingService:
    VERSION = "R71.5-v1"
    MARKET_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(
        self,
        *,
        market_data: Any,
        paper_auto_entry: Any | None = None,
        repository: BacktestResultsRepository | None = None,
        indicator_engine: IndicatorEngine | None = None,
    ) -> None:
        if market_data is None:
            raise TechnicalTradingValidationError("market_data is required")
        self.market_data = market_data
        self.paper_auto_entry = paper_auto_entry
        self._owns_repository = repository is None
        self.repository = repository or BacktestResultsRepository()
        self.indicators = indicator_engine or IndicatorEngine()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _date_label(value: Any) -> str:
        try:
            return pd.Timestamp(value).isoformat()
        except Exception:
            return str(value)

    @staticmethod
    def _number(
        name: str,
        value: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        message = f"{name} must be between {minimum} and {maximum}"
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise TechnicalTradingValidationError(message) from None
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise TechnicalTradingValidationError(message)
        return number

    @staticmethod
    def _symbol(value: Any) -> str:
        symbol = str(value or "").strip().upper()
        if not symbol:
            raise TechnicalTradingValidationError("symbol is required")
        if len(symbol) > 30:
            raise TechnicalTradingValidationError(
                "symbol must be 30 characters or fewer"
            )
        return symbol

    @classmethod
    def _symbols(cls, values: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            symbol = cls._symbol(value)
            if symbol not in seen:
                ordered.append(symbol)
                seen.add(symbol)
        if not ordered:
            raise TechnicalTradingValidationError("at least one symbol is required")
        if len(ordered) > 100:
            raise TechnicalTradingValidationError(
                "technical paper scan supports at most 100 symbols"
            )
        return ordered

    @staticmethod
    def _period(mode: str, period: str | None) -> tuple[Any, str]:
        try:
            profile = strategy_profile(mode)
        except ValueError:
            raise TechnicalTradingValidationError(
                "mode must be intraday or swing"
            ) from None
        resolved = str(period or profile.default_period).strip().lower()
        if resolved not in profile.allowed_periods:
            raise TechnicalTradingValidationError(
                f"{profile.mode} period must be one of: "
                + ", ".join(profile.allowed_periods)
            )
        return profile, resolved

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
                stamp = stamp.tz_localize(cls.MARKET_TZ)
            except Exception:
                return None
        else:
            try:
                stamp = stamp.tz_convert(cls.MARKET_TZ)
            except Exception:
                return None
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
            raise TechnicalTradingValidationError("No historical market data returned")
        result = frame.sort_index().copy()
        current = now or datetime.now(cls.MARKET_TZ)
        if current.tzinfo is None:
            current = current.replace(tzinfo=cls.MARKET_TZ)
        else:
            current = current.astimezone(cls.MARKET_TZ)

        if pd.api.types.is_numeric_dtype(result.index.dtype):
            raise TechnicalTradingValidationError(
                "Historical candles require valid timestamps"
            )
        if result.index.has_duplicates:
            raise TechnicalTradingValidationError(
                "Historical candles contain duplicate timestamps"
            )
        stamps = [cls._as_ist(value) for value in result.index]
        if any(stamp is None for stamp in stamps):
            raise TechnicalTradingValidationError(
                "Historical candles require valid timestamps"
            )
        minutes = {
            "5m": 5,
            "10m": 10,
            "15m": 15,
            "30m": 30,
            "60m": 60,
            "1h": 60,
        }.get(interval)
        if interval == "1d":
            complete = [
                stamp is not None
                and (
                    stamp.date() < current.date()
                    or (
                        stamp.date() == current.date()
                        and current.time() >= time(15, 30)
                    )
                )
                for stamp in stamps
            ]
            result = result.loc[complete]
        elif minutes is not None:
            result = result.loc[
                [
                    stamp is not None and stamp + timedelta(minutes=minutes) <= current
                    for stamp in stamps
                ]
            ]

        if result.empty:
            raise TechnicalTradingValidationError("No completed candles available")
        return result

    @classmethod
    def _execution_block_reason(
        cls, frame: pd.DataFrame, *, mode: str, now: datetime
    ) -> str | None:
        current = (
            now.replace(tzinfo=cls.MARKET_TZ)
            if now.tzinfo is None
            else now.astimezone(cls.MARKET_TZ)
        )
        stamp = cls._as_ist(frame.index[-1])
        if stamp is None:
            return "invalid_candle_timestamp"
        if mode == "intraday":
            if current.weekday() >= 5 or not time(9, 15) <= current.time() < time(
                14, 45
            ):
                return "intraday_entry_window_closed"
            if stamp.time() < time(9, 15):
                return "invalid_session_candle"
            close_at = stamp + timedelta(minutes=15)
            if (
                stamp.date() != current.date()
                or not 0 <= (current - close_at).total_seconds() < 900
            ):
                return "stale_candles"
            return None
        expected = current.date()
        if current.time() < time(15, 30):
            expected -= timedelta(days=1)
        while expected.weekday() >= 5:
            expected -= timedelta(days=1)
        return None if stamp.date() == expected else "stale_candles"

    @staticmethod
    def _scan_error(
        *,
        symbol: str,
        mode: str,
        interval: str,
        unavailable: bool = False,
        error: Exception | None = None,
    ) -> dict[str, Any]:
        reference = uuid4().hex[:12]
        validation = isinstance(error, TechnicalTradingValidationError)
        code = (
            "TECHNICAL_VALIDATION_FAILED"
            if validation
            else "MARKET_DATA_UNAVAILABLE"
            if unavailable
            else "TECHNICAL_ANALYSIS_FAILED"
        )
        logger.warning(
            "technical_scan_symbol_failed code=%s error_type=%s reference=%s",
            code,
            type(error).__name__ if error is not None else "ProviderFailure",
            reference,
        )
        message = (
            str(error)
            if validation
            else (
                "Kite candle data is unavailable"
                if unavailable
                else "Technical analysis failed"
            )
        )
        return {
            "symbol": symbol,
            "mode": mode,
            "interval": interval,
            "signal": "ERROR",
            "score": 0.0,
            "confidence": 0.0,
            "execution_eligible": False,
            "error": message if validation else f"{message} (reference: {reference})",
            "error_code": code,
            "error_reference": reference,
            "fundamentals_used": False,
        }

    @classmethod
    def _intraday_entry_window_open(cls, row: pd.Series) -> bool:
        stamp = cls._as_ist(row.name)
        if stamp is None:
            return True
        return stamp.time() < time(14, 45)

    @classmethod
    def _intraday_session_exit(cls, row: pd.Series) -> bool:
        stamp = cls._as_ist(row.name)
        if stamp is None:
            return False
        return stamp.time() >= time(14, 45)

    def _provider_observation(self, symbols: list[str]) -> dict[str, Any]:
        method = getattr(self.market_data, "observability_snapshot", None)
        if not callable(method):
            return {}
        try:
            payload = method(symbols)
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        # Provider diagnostics can contain exception text, URLs and credentials.
        # Keep useful attribution counts without forwarding those diagnostics.
        safe: dict[str, Any] = {}
        for name in (
            "fallback_count",
            "nse_resolution_count",
            "circuit_skip_count",
            "nse_resolver_attempts",
            "nse_resolver_skips",
        ):
            value = payload.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                safe[name] = value
        counts = payload.get("provider_counts")
        if isinstance(counts, dict):
            safe["provider_counts"] = {
                name: count
                for name, count in counts.items()
                if isinstance(name, str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", name)
                and isinstance(count, int)
                and not isinstance(count, bool)
                and count >= 0
            }
        errors = payload.get("provider_errors_by_symbol")
        if isinstance(errors, dict):
            safe["provider_error_count"] = sum(
                len(values) for values in errors.values() if isinstance(values, list)
            )
        return safe

    @classmethod
    def _market_health(cls, payload: Any) -> dict[str, Any]:
        """Project readiness without upstream exception strings or transport data."""
        if not isinstance(payload, dict):
            return {"status": "unknown"}
        status = payload.get("status")
        safe: dict[str, Any] = {
            "status": status
            if isinstance(status, str)
            and status
            in {
                "healthy",
                "ok",
                "configured",
                "degraded",
                "unavailable",
                "unknown",
            }
            else "unknown",
        }
        for name in ("provider",):
            value = payload.get(name)
            if isinstance(value, str) and re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_]{0,79}", value
            ):
                safe[name] = value
        for name in ("runtime_status", "auth_status"):
            value = payload.get(name)
            if isinstance(value, str) and value in {
                "runtime_verified",
                "not_probed",
                "failed",
                "configured",
                "not_configured",
                "api_key_missing",
                "access_token_missing",
            }:
                safe[name] = value
        for name in ("authenticated", "fallback_on_error"):
            if isinstance(payload.get(name), bool):
                safe[name] = payload[name]
        value = payload.get("max_workers")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            safe["max_workers"] = value
        providers = payload.get("providers")
        if isinstance(providers, list):
            safe["providers"] = [
                name
                for name in providers
                if isinstance(name, str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", name)
            ]
        nested = payload.get("provider_health")
        if isinstance(nested, dict):
            safe["provider_health"] = (
                cls._market_health(nested)
                if "status" in nested
                else {
                    name: cls._market_health(health)
                    for name, health in nested.items()
                    if isinstance(name, str)
                    and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", name)
                }
            )
        return safe

    def readiness(self) -> dict[str, Any]:
        health = self._market_health(
            self.market_data.health()
            if callable(getattr(self.market_data, "health", None))
            else {"status": "unknown"}
        )
        paper = (
            self.paper_auto_entry.health()
            if self.paper_auto_entry is not None
            and callable(getattr(self.paper_auto_entry, "health", None))
            else {"status": "unavailable"}
        )
        return {
            "status": "ready",
            "version": self.VERSION,
            "data_policy": "kite_only",
            "fundamentals_used": False,
            "enrichment_used": False,
            "broker_orders_allowed": False,
            "paper_only_execution": True,
            "backtest_engine": {
                "name": "TechnicalRealisticBacktestEngine",
                "version": TechnicalRealisticBacktestEngine.ENGINE_VERSION,
                "execution_model": (TechnicalRealisticBacktestEngine.EXECUTION_MODEL),
                "same_bar_priority": "stop",
                "intraday_forced_exit_ist": "15:00",
                "atr_bracket_execution": True,
            },
            "profiles": {
                mode: {
                    "interval": strategy_profile(mode).interval,
                    "default_period": strategy_profile(mode).default_period,
                    "allowed_periods": list(strategy_profile(mode).allowed_periods),
                    "entry_score": strategy_profile(mode).entry_score,
                    "stop_atr": strategy_profile(mode).stop_atr,
                    "reward_risk": strategy_profile(mode).reward_risk,
                }
                for mode in ("intraday", "swing")
            },
            "market_data": health,
            "paper_auto_entry": paper,
            "indicator_engine": (
                self.indicators.health()
                if callable(getattr(self.indicators, "health", None))
                else {"status": "unknown"}
            ),
            "strategy_registry": registry_readiness(),
            "strategy_execution_wiring": {
                "legacy_profile_service": "retained_for_R71.5_compatibility",
                "multi_strategy_scanner": "R72.5.2_available",
            },
        }

    def scan(
        self,
        *,
        symbols: list[str],
        mode: str,
        period: str | None = None,
        top_n: int = 20,
        execute_paper: bool = False,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        profile, resolved_period = self._period(mode, period)
        requested = self._symbols(symbols)
        top_n = int(self._number("top_n", top_n, minimum=1, maximum=100))
        run_id = str(run_id or "").strip() or f"tech-{uuid4().hex}"

        begin = getattr(self.market_data, "begin_observation", None)
        if callable(begin):
            begin()

        frames, _failures = self.market_data.batch_candles_with_errors(
            requested,
            period=resolved_period,
            interval=profile.interval,
        )
        observed_now = now or datetime.now(self.MARKET_TZ)

        results: list[dict[str, Any]] = []
        for symbol in requested:
            raw = frames.get(symbol)
            if raw is None:
                results.append(
                    self._scan_error(
                        symbol=symbol,
                        mode=profile.mode,
                        interval=profile.interval,
                        unavailable=True,
                    )
                )
                continue

            try:
                completed = self._completed_bars(
                    raw,
                    interval=profile.interval,
                    now=observed_now,
                )
                if len(completed) < 60:
                    raise TechnicalTradingValidationError(
                        "At least 60 completed candles are required"
                    )
                frame = self.indicators.calculate(completed.copy())
                signal = latest_signal(frame, profile)
                risk = signal["risk"]
                block_reason = self._execution_block_reason(
                    frame,
                    mode=profile.mode,
                    now=observed_now,
                )
                eligible = bool(
                    signal["signal"] == "BUY"
                    and risk.get("entry")
                    and risk.get("stoploss")
                    and risk.get("target2")
                    and block_reason is None
                )
                results.append(
                    {
                        "symbol": symbol,
                        "mode": profile.mode,
                        "interval": profile.interval,
                        "bar_at": self._date_label(frame.index[-1]),
                        "signal": signal["signal"],
                        "score": signal["score"],
                        "confidence": signal["confidence"],
                        "trigger": signal["trigger"],
                        "execution_eligible": eligible,
                        "execution_blocked_reason": block_reason,
                        "entry": risk.get("entry"),
                        "stoploss": risk.get("stoploss"),
                        "target2": risk.get("target2"),
                        "reward_risk": risk.get("reward_risk"),
                        "technical_evidence": signal["evidence"],
                        "indicators": signal["indicators"],
                        "fundamentals_used": False,
                    }
                )
            except Exception as exc:
                results.append(
                    self._scan_error(
                        symbol=symbol,
                        mode=profile.mode,
                        interval=profile.interval,
                        error=exc,
                    )
                )

        ranked = sorted(
            [item for item in results if item.get("signal") != "ERROR"],
            key=lambda item: (
                bool(item.get("execution_eligible")),
                float(item.get("score") or 0.0),
            ),
            reverse=True,
        )
        candidates = [item for item in ranked if item.get("execution_eligible")][:top_n]

        paper_candidates = []
        for item in candidates:
            paper_candidates.append(
                {
                    "symbol": item["symbol"],
                    "execution_eligible": True,
                    "ranking_score": item["score"],
                    "confidence": item["confidence"],
                    "signal": {
                        "signal": "BUY",
                        "overall_score": item["score"],
                        "confidence": item["confidence"],
                        "entry": item["entry"],
                        "stoploss": item["stoploss"],
                        "target2": item["target2"],
                    },
                    "technical_mode": profile.mode,
                    "technical_trigger": item.get("trigger"),
                }
            )

        paper_result: dict[str, Any]
        if self.paper_auto_entry is None:
            paper_result = {
                "status": "unavailable",
                "opened": [],
                "reason": "paper_auto_entry_service_unavailable",
            }
        else:
            paper_result = self.paper_auto_entry.process_scan(
                {
                    "outcome": "completed",
                    "top_picks": paper_candidates,
                    "execution_top_picks": paper_candidates,
                },
                run_id=run_id,
                execute_requested=bool(execute_paper),
                continuation=False,
                now=now,
            )

        return {
            "status": "completed",
            "run_id": run_id,
            "mode": profile.mode,
            "period": resolved_period,
            "interval": profile.interval,
            "requested_symbols": len(requested),
            "completed_symbols": sum(
                1 for item in results if item.get("signal") != "ERROR"
            ),
            "error_symbols": sum(
                1 for item in results if item.get("signal") == "ERROR"
            ),
            "buy_candidates": len(candidates),
            "results": ranked
            + [item for item in results if item.get("signal") == "ERROR"],
            "top_picks": candidates,
            "paper": paper_result,
            "provider_observation": self._provider_observation(requested),
            "safety": {
                "fundamentals_used": False,
                "broker_orders_allowed": False,
                "paper_execution_requested": bool(execute_paper),
                "paper_risk_governance_reused": True,
            },
        }

    def backtest(
        self,
        *,
        symbol: str,
        mode: str,
        period: str | None = None,
        capital: float = 100_000.0,
        cost_bps: float = 0.0,
        slippage_bps: float = 0.0,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        profile, resolved_period = self._period(mode, period)
        symbol = self._symbol(symbol)
        capital = self._number(
            "capital",
            capital,
            minimum=1_000.0,
            maximum=1_000_000_000.0,
        )
        cost_bps = self._number(
            "cost_bps",
            cost_bps,
            minimum=0.0,
            maximum=1_000.0,
        )
        slippage_bps = self._number(
            "slippage_bps",
            slippage_bps,
            minimum=0.0,
            maximum=1_000.0,
        )
        run_id = str(run_id or "").strip() or f"tech-bt-{uuid4().hex}"
        if self.repository.by_run_id(run_id) is not None:
            raise TechnicalTradingValidationError("backtest run_id already exists")

        begin = getattr(self.market_data, "begin_observation", None)
        if callable(begin):
            begin()

        raw = self.market_data.candles(
            symbol,
            period=resolved_period,
            interval=profile.interval,
        )
        completed = self._completed_bars(
            raw,
            interval=profile.interval,
            now=now,
        )
        if len(completed) < 60:
            raise TechnicalTradingValidationError(
                "Backtest requires at least 60 completed candles"
            )
        frame = self.indicators.calculate(completed.copy())

        def entry_rule(
            previous: pd.Series,
            current: pd.Series,
        ) -> dict[str, Any] | None:
            if profile.mode == "intraday" and not self._intraday_entry_window_open(
                current
            ):
                return None
            return entry_decision(previous, current, profile)

        def exit_rule(
            previous: pd.Series,
            current: pd.Series,
        ) -> dict[str, Any] | None:
            return exit_decision(previous, current, profile)

        simulation = TechnicalRealisticBacktestEngine(
            TechnicalRealisticConfig(
                initial_capital=capital,
                cost_bps=cost_bps,
                slippage_bps=slippage_bps,
                force_final_exit=True,
                same_bar_priority="stop",
                intraday_exit_hour=15,
                intraday_exit_minute=0,
            )
        ).run(
            frame,
            entry_rule=entry_rule,
            exit_rule=exit_rule,
            mode=profile.mode,
        )

        metrics = simulation.metrics
        strategy_name = f"TECHNICAL_{profile.mode.upper()}"
        strategy_version = self.VERSION
        created_at = self._timestamp()
        result = {
            "status": "completed",
            "run_id": run_id,
            "engine": {
                "name": "TechnicalRealisticBacktestEngine",
                "version": TechnicalRealisticBacktestEngine.ENGINE_VERSION,
                "execution_model": (TechnicalRealisticBacktestEngine.EXECUTION_MODEL),
                "position_sizing": (TechnicalRealisticBacktestEngine.POSITION_SIZING),
            },
            "strategy": {
                "name": strategy_name,
                "version": strategy_version,
                "technical_only": True,
                "mode": profile.mode,
                "entry_score": profile.entry_score,
                "exit_score": profile.exit_score,
                "stop_atr_reference": profile.stop_atr,
                "reward_risk_reference": profile.reward_risk,
            },
            "symbol": symbol,
            "period": resolved_period,
            "interval": profile.interval,
            "start_date": self._date_label(frame.index[0]),
            "end_date": self._date_label(frame.index[-1]),
            "bars": len(frame),
            "metrics": metrics,
            "trades": simulation.trades,
            "equity_curve": simulation.equity_curve,
            "provider_observation": self._provider_observation([symbol]),
            "parameters": {
                "capital": round(capital, 2),
                "cost_bps": round(cost_bps, 4),
                "slippage_bps": round(slippage_bps, 4),
                "mode": profile.mode,
                "period": resolved_period,
                "interval": profile.interval,
                "entry_score": profile.entry_score,
                "atr_bracket_execution": True,
                "same_bar_priority": "stop",
                "intraday_forced_session_exit": (profile.mode == "intraday"),
                "intraday_forced_exit_ist": (
                    "15:00" if profile.mode == "intraday" else None
                ),
            },
            "created_at": created_at,
            "safety": {
                "historical_simulation_only": True,
                "fundamentals_used": False,
                "broker_orders_allowed": False,
                "paper_orders_created": False,
            },
        }

        self.repository.save(
            {
                "run_id": run_id,
                "strategy_name": strategy_name,
                "strategy_version": strategy_version,
                "status": "completed",
                "symbol": symbol,
                "timeframe": profile.interval,
                "start_date": result["start_date"],
                "end_date": result["end_date"],
                "total_trades": metrics["total_trades"],
                "win_rate": metrics["win_rate"],
                "net_profit": metrics["net_profit"],
                "max_drawdown": metrics["max_drawdown_pct"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "initial_capital": metrics["initial_capital"],
                "final_capital": metrics["final_capital"],
                "return_pct": metrics["return_pct"],
                "buy_hold_return_pct": metrics["buy_hold_return_pct"],
                "profit_factor": metrics["profit_factor"],
                "expectancy": metrics["expectancy"],
                "exposure_pct": metrics["exposure_pct"],
                "cost_bps": cost_bps,
                "slippage_bps": slippage_bps,
                "parameters": result["parameters"],
                "result": result,
                "created_at": created_at,
            }
        )
        return result

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()


__all__ = ["TechnicalTradingService", "TechnicalTradingValidationError"]
