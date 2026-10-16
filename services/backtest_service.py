"""Canonical TrendForge backtesting service.

R68.4 deliberately starts with one transparent, versioned strategy:
EMA20/EMA50 bullish crossover confirmed by RSI and EMA20 proximity.

Signals are calculated from a completed daily bar and filled at the next
bar's open. This avoids same-close look-ahead execution.
"""
from __future__ import annotations

import math
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pandas as pd

from backtest.backtest_engine import BacktestConfig, BacktestEngine
from database.repositories.backtest_results import (
    BacktestResultsRepository,
)
from indicators.indicator_engine import IndicatorEngine


class BacktestBusyError(RuntimeError):
    """Raised when the process already owns an active backtest."""


class BacktestNotFoundError(LookupError):
    """Raised when a persisted backtest run cannot be found."""


class BacktestService:
    STRATEGY_NAME = "EMA20_50_RSI"
    STRATEGY_VERSION = "R68.4-v1"
    ALLOWED_PERIODS = {"1y", "2y", "5y"}
    ALLOWED_INTERVALS = {"1d"}

    def __init__(
        self,
        *,
        market_data: Any,
        repository: BacktestResultsRepository | None = None,
        indicator_engine: IndicatorEngine | None = None,
    ) -> None:
        if market_data is None:
            raise ValueError("market_data is required")
        self.market_data = market_data
        self._owns_repository = repository is None
        self.repository = repository or BacktestResultsRepository()
        self.indicators = indicator_engine or IndicatorEngine()
        self._run_lock = threading.Lock()
        self._active_run_id: str | None = None

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
    def _finite(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _normalized_symbol(value: Any) -> str:
        symbol = str(value or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if len(symbol) > 30:
            raise ValueError("symbol must be 30 characters or fewer")
        return symbol

    @staticmethod
    def _validate_number(
        name: str,
        value: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite")
        if not minimum <= number <= maximum:
            raise ValueError(
                f"{name} must be between {minimum} and {maximum}"
            )
        return number

    @staticmethod
    def _is_cross_up(previous: pd.Series, current: pd.Series) -> bool:
        values = (
            previous.get("EMA_20"),
            previous.get("EMA_50"),
            current.get("EMA_20"),
            current.get("EMA_50"),
        )
        if any(pd.isna(value) for value in values):
            return False
        return bool(
            float(previous["EMA_20"])
            <= float(previous["EMA_50"])
            and float(current["EMA_20"])
            > float(current["EMA_50"])
        )

    @staticmethod
    def _is_cross_down(previous: pd.Series, current: pd.Series) -> bool:
        values = (
            previous.get("EMA_20"),
            previous.get("EMA_50"),
            current.get("EMA_20"),
            current.get("EMA_50"),
        )
        if any(pd.isna(value) for value in values):
            return False
        return bool(
            float(previous["EMA_20"])
            >= float(previous["EMA_50"])
            and float(current["EMA_20"])
            < float(current["EMA_50"])
        )

    @staticmethod
    def _ema_proximity_pct(row: pd.Series) -> float | None:
        close = BacktestService._finite(row.get("close"))
        ema20 = BacktestService._finite(row.get("EMA_20"))
        if close is None or ema20 is None or ema20 <= 0:
            return None
        return abs(close - ema20) * 100.0 / ema20

    @staticmethod
    def _fill_price(
        raw_price: float,
        *,
        side: str,
        slippage_bps: float,
    ) -> float:
        rate = float(slippage_bps) / 10_000.0
        if side == "BUY":
            return float(raw_price) * (1.0 + rate)
        return float(raw_price) * (1.0 - rate)

    @staticmethod
    def _transaction_cost(
        notional: float,
        *,
        cost_bps: float,
    ) -> float:
        return float(notional) * float(cost_bps) / 10_000.0

    @staticmethod
    def _profit_factor(trades: list[dict[str, Any]]) -> float | None:
        wins = sum(
            max(0.0, float(item.get("net_pnl") or 0.0))
            for item in trades
        )
        losses = abs(
            sum(
                min(0.0, float(item.get("net_pnl") or 0.0))
                for item in trades
            )
        )
        if losses > 0:
            return round(wins / losses, 4)
        if wins > 0:
            return None
        return 0.0

    @staticmethod
    def _equity_returns(
        equity_curve: list[dict[str, Any]],
    ) -> list[float]:
        values = [
            float(item["equity"])
            for item in equity_curve
            if item.get("equity") is not None
        ]
        returns: list[float] = []
        for previous, current in zip(values, values[1:]):
            if previous > 0:
                returns.append(current / previous - 1.0)
        return returns

    def readiness(self) -> dict[str, Any]:
        health = (
            self.market_data.health()
            if callable(getattr(self.market_data, "health", None))
            else {"status": "unknown"}
        )
        return {
            "status": "ready",
            "strategy": self.STRATEGY_NAME,
            "strategy_version": self.STRATEGY_VERSION,
            "allowed_periods": sorted(self.ALLOWED_PERIODS),
            "allowed_intervals": sorted(self.ALLOWED_INTERVALS),
            "execution_model": "signal_close_fill_next_open",
            "long_only": True,
            "single_position": True,
            "broker_orders_allowed": False,
            "paper_orders_created": False,
            "active_run_id": self._active_run_id,
            "market_data": health,
            "persisted_runs": self.repository.count(),
        }

    def history(
        self,
        *,
        limit: int = 50,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        if symbol:
            rows = self.repository.by_symbol(
                self._normalized_symbol(symbol),
                limit,
            )
        else:
            rows = self.repository.latest(limit)

        compact = []
        for row in rows:
            compact.append(
                {
                    key: row.get(key)
                    for key in (
                        "id",
                        "run_id",
                        "strategy_name",
                        "strategy_version",
                        "status",
                        "symbol",
                        "timeframe",
                        "start_date",
                        "end_date",
                        "total_trades",
                        "win_rate",
                        "net_profit",
                        "max_drawdown",
                        "sharpe_ratio",
                        "initial_capital",
                        "final_capital",
                        "return_pct",
                        "buy_hold_return_pct",
                        "profit_factor",
                        "expectancy",
                        "exposure_pct",
                        "cost_bps",
                        "slippage_bps",
                        "created_at",
                    )
                }
            )
        return {
            "status": "ready",
            "returned": len(compact),
            "runs": compact,
        }

    def get(self, run_id: str) -> dict[str, Any]:
        normalized = str(run_id or "").strip()
        if not normalized:
            raise ValueError("run_id is required")
        row = self.repository.by_run_id(normalized)
        if row is None:
            raise BacktestNotFoundError(
                f"Backtest run not found: {normalized}"
            )

        result = row.get("result")
        if isinstance(result, dict) and result:
            return result
        return {
            "status": row.get("status") or "legacy_summary",
            "run_id": row.get("run_id"),
            "strategy": {
                "name": row.get("strategy_name"),
                "version": row.get("strategy_version"),
            },
            "symbol": row.get("symbol"),
            "period": row.get("parameters", {}).get("period"),
            "interval": row.get("timeframe"),
            "metrics": {
                "total_trades": row.get("total_trades"),
                "win_rate": row.get("win_rate"),
                "net_profit": row.get("net_profit"),
                "max_drawdown_pct": row.get("max_drawdown"),
                "sharpe_ratio": row.get("sharpe_ratio"),
                "initial_capital": row.get("initial_capital"),
                "final_capital": row.get("final_capital"),
                "return_pct": row.get("return_pct"),
                "buy_hold_return_pct": row.get(
                    "buy_hold_return_pct"
                ),
                "profit_factor": row.get("profit_factor"),
                "expectancy": row.get("expectancy"),
                "exposure_pct": row.get("exposure_pct"),
            },
            "parameters": row.get("parameters") or {},
            "trades": [],
            "equity_curve": [],
            "created_at": row.get("created_at"),
        }

    def run(
        self,
        *,
        symbol: str,
        period: str = "2y",
        interval: str = "1d",
        capital: float = 100_000.0,
        rsi_threshold: float = 60.0,
        ema_proximity_pct: float = 1.0,
        cost_bps: float = 0.0,
        slippage_bps: float = 0.0,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        symbol = self._normalized_symbol(symbol)
        period = str(period or "").strip().lower()
        interval = str(interval or "").strip().lower()

        if period not in self.ALLOWED_PERIODS:
            raise ValueError(
                "period must be one of: "
                + ", ".join(sorted(self.ALLOWED_PERIODS))
            )
        if interval not in self.ALLOWED_INTERVALS:
            raise ValueError("interval must be 1d")

        capital = self._validate_number(
            "capital",
            capital,
            minimum=1_000.0,
            maximum=1_000_000_000.0,
        )
        rsi_threshold = self._validate_number(
            "rsi_threshold",
            rsi_threshold,
            minimum=0.0,
            maximum=100.0,
        )
        ema_proximity_pct = self._validate_number(
            "ema_proximity_pct",
            ema_proximity_pct,
            minimum=0.0,
            maximum=20.0,
        )
        cost_bps = self._validate_number(
            "cost_bps",
            cost_bps,
            minimum=0.0,
            maximum=1_000.0,
        )
        slippage_bps = self._validate_number(
            "slippage_bps",
            slippage_bps,
            minimum=0.0,
            maximum=1_000.0,
        )

        resolved_run_id = (
            str(run_id or "").strip()
            or f"bt-{uuid4().hex}"
        )
        if self.repository.by_run_id(resolved_run_id) is not None:
            raise ValueError(
                f"backtest run_id already exists: {resolved_run_id}"
            )

        if not self._run_lock.acquire(blocking=False):
            raise BacktestBusyError(
                "Another backtest is already running"
            )
        self._active_run_id = resolved_run_id
        try:
            return self._run_locked(
                run_id=resolved_run_id,
                symbol=symbol,
                period=period,
                interval=interval,
                capital=capital,
                rsi_threshold=rsi_threshold,
                ema_proximity_pct=ema_proximity_pct,
                cost_bps=cost_bps,
                slippage_bps=slippage_bps,
            )
        finally:
            self._active_run_id = None
            self._run_lock.release()

    def _run_locked(
        self,
        *,
        run_id: str,
        symbol: str,
        period: str,
        interval: str,
        capital: float,
        rsi_threshold: float,
        ema_proximity_pct: float,
        cost_bps: float,
        slippage_bps: float,
    ) -> dict[str, Any]:
        begin = getattr(self.market_data, "begin_observation", None)
        if callable(begin):
            begin()

        candles = self.market_data.candles(
            symbol,
            period=period,
            interval=interval,
        )
        if not isinstance(candles, pd.DataFrame) or candles.empty:
            raise ValueError(
                f"No historical market data returned for {symbol}"
            )
        if len(candles) < 60:
            raise ValueError(
                "Backtest requires at least 60 daily candles"
            )

        frame = self.indicators.calculate(candles.copy())
        if len(frame) < 60:
            raise ValueError(
                "Indicator pipeline returned insufficient history"
            )

        def entry_rule(
            previous: pd.Series,
            row: pd.Series,
        ) -> dict[str, Any] | None:
            rsi = self._finite(row.get("RSI"))
            proximity = self._ema_proximity_pct(row)
            if (
                self._is_cross_up(previous, row)
                and rsi is not None
                and rsi >= rsi_threshold
                and proximity is not None
                and proximity <= ema_proximity_pct
            ):
                return {
                    "rsi": rsi,
                    "ema_proximity_pct": proximity,
                }
            return None

        def exit_rule(
            previous: pd.Series,
            row: pd.Series,
        ) -> dict[str, Any] | None:
            rsi = self._finite(row.get("RSI"))
            cross_down = self._is_cross_down(previous, row)
            rsi_exit = (
                rsi is not None
                and rsi < rsi_threshold
            )
            if not cross_down and not rsi_exit:
                return None
            return {
                "reason": (
                    "EMA20_CROSS_BELOW_EMA50"
                    if cross_down
                    else "RSI_BELOW_THRESHOLD"
                )
            }

        simulation = BacktestEngine(
            BacktestConfig(
                initial_capital=capital,
                cost_bps=cost_bps,
                slippage_bps=slippage_bps,
                force_final_exit=True,
            )
        ).run(
            frame,
            entry_rule=entry_rule,
            exit_rule=exit_rule,
        )
        trades = simulation.trades
        equity_curve = simulation.equity_curve
        metrics = simulation.metrics

        provider_observation = {}
        observation = getattr(
            self.market_data,
            "observability_snapshot",
            None,
        )
        if callable(observation):
            try:
                observed = observation([symbol])
                if isinstance(observed, dict):
                    provider_observation = observed
            except Exception:
                provider_observation = {}

        parameters = {
            "period": period,
            "interval": interval,
            "capital": round(capital, 2),
            "rsi_threshold": round(rsi_threshold, 4),
            "ema_proximity_pct": round(
                ema_proximity_pct,
                4,
            ),
            "cost_bps": round(cost_bps, 4),
            "slippage_bps": round(slippage_bps, 4),
            "position_sizing": BacktestEngine.POSITION_SIZING,
            "execution_model": BacktestEngine.EXECUTION_MODEL,
            "forced_final_exit": True,
        }
        metrics = {
            "initial_capital": round(capital, 2),
            "final_capital": round(cash, 2),
            "net_profit": round(net_profit, 2),
            "return_pct": round(return_pct, 4),
            "buy_hold_return_pct": round(
                buy_hold_return,
                4,
            ),
            "excess_vs_buy_hold_pct": round(
                return_pct - buy_hold_return,
                4,
            ),
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 4),
            "average_win": round(average_win, 2),
            "average_loss": round(average_loss, 2),
            "expectancy": round(expectancy, 2),
            "profit_factor": self._profit_factor(trades),
            "max_drawdown_pct": round(
                float(max_drawdown),
                4,
            ),
            "sharpe_ratio": round(float(sharpe), 4),
            "exposure_pct": round(exposure_pct, 4),
            "transaction_costs": round(
                total_transaction_costs,
                2,
            ),
            "slippage_impact_estimate": round(
                total_slippage_impact,
                2,
            ),
        }

        result = {
            "status": "completed",
            "run_id": run_id,
            "strategy": {
                "name": self.STRATEGY_NAME,
                "version": self.STRATEGY_VERSION,
                "entry": (
                    "EMA20 crosses above EMA50, RSI >= threshold, "
                    "close within configured EMA20 proximity"
                ),
                "exit": (
                    "EMA20 crosses below EMA50 or RSI < threshold"
                ),
            },
            "symbol": symbol,
            "period": period,
            "interval": interval,
            "start_date": self._date_label(frame.index[0]),
            "end_date": self._date_label(frame.index[-1]),
            "bars": len(frame),
            "parameters": parameters,
            "metrics": metrics,
            "trades": trades,
            "equity_curve": equity_curve,
            "provider_observation": provider_observation,
            "created_at": self._timestamp(),
            "safety": {
                "historical_simulation_only": True,
                "broker_orders_allowed": False,
                "paper_orders_created": False,
            },
        }

        self.repository.save(
            {
                "run_id": run_id,
                "strategy_name": self.STRATEGY_NAME,
                "strategy_version": self.STRATEGY_VERSION,
                "status": "completed",
                "symbol": symbol,
                "timeframe": interval,
                "start_date": result["start_date"],
                "end_date": result["end_date"],
                "total_trades": metrics["total_trades"],
                "win_rate": metrics["win_rate"],
                "net_profit": metrics["net_profit"],
                "max_drawdown": metrics[
                    "max_drawdown_pct"
                ],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "initial_capital": metrics[
                    "initial_capital"
                ],
                "final_capital": metrics["final_capital"],
                "return_pct": metrics["return_pct"],
                "buy_hold_return_pct": metrics[
                    "buy_hold_return_pct"
                ],
                "profit_factor": metrics[
                    "profit_factor"
                ],
                "expectancy": metrics["expectancy"],
                "exposure_pct": metrics["exposure_pct"],
                "cost_bps": cost_bps,
                "slippage_bps": slippage_bps,
                "parameters": parameters,
                "result": result,
                "created_at": result["created_at"],
            }
        )
        return result

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()


__all__ = [
    "BacktestBusyError",
    "BacktestNotFoundError",
    "BacktestService",
]
