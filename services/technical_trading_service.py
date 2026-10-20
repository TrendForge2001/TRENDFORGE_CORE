"""Technical-only scanner, paper-trading handoff and backtest service.

R71.2 keeps fundamentals/enrichment outside this path. Historical OHLCV is
expected from a Kite-only market-data adapter. Technical signals use the
canonical IndicatorEngine and the same profile definitions for paper scans and
historical backtests.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import math
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.backtest_engine import BacktestEngine
from backtest.technical_realistic_engine import (
    TechnicalRealisticBacktestEngine,
    TechnicalRealisticConfig,
)
from database.repositories.backtest_results import BacktestResultsRepository
from indicators.indicator_engine import IndicatorEngine
from scanner.technical_strategy import (
    entry_decision,
    exit_decision,
    latest_signal,
    strategy_profile,
)
from scanner.strategy_registry import registry_readiness


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
            raise ValueError("market_data is required")
        self.market_data = market_data
        self.paper_auto_entry = paper_auto_entry
        self._owns_repository = repository is None
        self.repository = repository or BacktestResultsRepository()
        self.indicators = indicator_engine or IndicatorEngine()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

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
        number = float(value)
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return number

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
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            symbol = cls._symbol(value)
            if symbol not in seen:
                ordered.append(symbol)
                seen.add(symbol)
        if not ordered:
            raise ValueError("at least one symbol is required")
        if len(ordered) > 100:
            raise ValueError("technical paper scan supports at most 100 symbols")
        return ordered

    @staticmethod
    def _period(mode: str, period: str | None) -> tuple[Any, str]:
        profile = strategy_profile(mode)
        resolved = str(period or profile.default_period).strip().lower()
        if resolved not in profile.allowed_periods:
            raise ValueError(
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
                return stamp
        else:
            try:
                stamp = stamp.tz_convert(cls.MARKET_TZ)
            except Exception:
                return stamp
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
        current = now or datetime.now(cls.MARKET_TZ)
        if current.tzinfo is None:
            current = current.replace(tzinfo=cls.MARKET_TZ)
        else:
            current = current.astimezone(cls.MARKET_TZ)

        last_stamp = cls._as_ist(result.index[-1])
        if last_stamp is None:
            return result

        if interval == "1d":
            if (
                last_stamp.date() == current.date()
                and current.time() < time(15, 30)
            ):
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
        return payload if isinstance(payload, dict) else {}

    def readiness(self) -> dict[str, Any]:
        health = (
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
                "execution_model": (
                    TechnicalRealisticBacktestEngine.EXECUTION_MODEL
                ),
                "same_bar_priority": "stop",
                "intraday_forced_exit_ist": "15:00",
                "atr_bracket_execution": True,
            },
            "profiles": {
                mode: {
                    "interval": strategy_profile(mode).interval,
                    "default_period": strategy_profile(mode).default_period,
                    "allowed_periods": list(
                        strategy_profile(mode).allowed_periods
                    ),
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

        frames, failures = self.market_data.batch_candles_with_errors(
            requested,
            period=resolved_period,
            interval=profile.interval,
        )

        results: list[dict[str, Any]] = []
        for symbol in requested:
            raw = frames.get(symbol)
            if raw is None:
                results.append(
                    {
                        "symbol": symbol,
                        "signal": "ERROR",
                        "score": 0.0,
                        "confidence": 0.0,
                        "execution_eligible": False,
                        "error": failures.get(
                            symbol,
                            "Kite returned no candle data",
                        ),
                    }
                )
                continue

            try:
                completed = self._completed_bars(
                    raw,
                    interval=profile.interval,
                    now=now,
                )
                if len(completed) < 60:
                    raise ValueError(
                        "At least 60 completed candles are required"
                    )
                frame = self.indicators.calculate(completed.copy())
                signal = latest_signal(frame, profile)
                risk = signal["risk"]
                eligible = bool(
                    signal["signal"] == "BUY"
                    and risk.get("entry")
                    and risk.get("stoploss")
                    and risk.get("target2")
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
                    {
                        "symbol": symbol,
                        "mode": profile.mode,
                        "interval": profile.interval,
                        "signal": "ERROR",
                        "score": 0.0,
                        "confidence": 0.0,
                        "execution_eligible": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "fundamentals_used": False,
                    }
                )

        ranked = sorted(
            [
                item
                for item in results
                if item.get("signal") != "ERROR"
            ],
            key=lambda item: (
                bool(item.get("execution_eligible")),
                float(item.get("score") or 0.0),
            ),
            reverse=True,
        )
        candidates = [
            item for item in ranked
            if item.get("execution_eligible")
        ][:top_n]

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
            "results": ranked + [
                item for item in results if item.get("signal") == "ERROR"
            ],
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
            raise ValueError(f"backtest run_id already exists: {run_id}")

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
            raise ValueError("Backtest requires at least 60 completed candles")
        frame = self.indicators.calculate(completed.copy())

        def entry_rule(
            previous: pd.Series,
            current: pd.Series,
        ) -> dict[str, Any] | None:
            if (
                profile.mode == "intraday"
                and not self._intraday_entry_window_open(current)
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
                "execution_model": (
                    TechnicalRealisticBacktestEngine.EXECUTION_MODEL
                ),
                "position_sizing": (
                    TechnicalRealisticBacktestEngine.POSITION_SIZING
                ),
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
                "intraday_forced_session_exit": (
                    profile.mode == "intraday"
                ),
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


__all__ = ["TechnicalTradingService"]
