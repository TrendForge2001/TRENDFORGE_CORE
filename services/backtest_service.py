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

from backtest.max_drawdown import MaxDrawdown
from backtest.sharpe_ratio import SharpeRatio
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

        cash = float(capital)
        position: dict[str, Any] | None = None
        pending_entry: dict[str, Any] | None = None
        pending_exit: dict[str, Any] | None = None
        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = [
            {
                "date": self._date_label(frame.index[0]),
                "equity": round(cash, 2),
                "cash": round(cash, 2),
                "market_value": 0.0,
            }
        ]
        invested_bar_count = 0
        total_transaction_costs = 0.0
        total_slippage_impact = 0.0

        first_open = self._finite(frame.iloc[0].get("open"))
        last_close = self._finite(frame.iloc[-1].get("close"))
        if first_open is None or first_open <= 0:
            raise ValueError("Initial open price is invalid")
        if last_close is None or last_close <= 0:
            raise ValueError("Final close price is invalid")

        for index in range(1, len(frame)):
            row = frame.iloc[index]
            previous = frame.iloc[index - 1]
            label = self._date_label(frame.index[index])
            raw_open = self._finite(row.get("open"))
            close = self._finite(row.get("close"))
            if raw_open is None or raw_open <= 0:
                raise ValueError(
                    f"Invalid open price at {label}"
                )
            if close is None or close <= 0:
                raise ValueError(
                    f"Invalid close price at {label}"
                )

            if pending_exit is not None and position is not None:
                exit_fill = self._fill_price(
                    raw_open,
                    side="SELL",
                    slippage_bps=slippage_bps,
                )
                exit_notional = (
                    float(position["quantity"]) * exit_fill
                )
                exit_cost = self._transaction_cost(
                    exit_notional,
                    cost_bps=cost_bps,
                )
                cash += exit_notional - exit_cost
                total_transaction_costs += exit_cost
                total_slippage_impact += (
                    float(position["quantity"])
                    * raw_open
                    * slippage_bps
                    / 10_000.0
                )

                gross_pnl = (
                    exit_fill - float(position["entry_price"])
                ) * int(position["quantity"])
                net_pnl = (
                    gross_pnl
                    - float(position["entry_cost"])
                    - exit_cost
                )
                basis = (
                    float(position["entry_price"])
                    * int(position["quantity"])
                    + float(position["entry_cost"])
                )
                trade_return = (
                    net_pnl * 100.0 / basis
                    if basis > 0
                    else 0.0
                )

                trades.append(
                    {
                        "trade_number": len(trades) + 1,
                        "side": "LONG",
                        "entry_signal_at": position[
                            "entry_signal_at"
                        ],
                        "entry_at": position["entry_at"],
                        "entry_price": round(
                            float(position["entry_price"]),
                            6,
                        ),
                        "entry_raw_open": round(
                            float(position["entry_raw_open"]),
                            6,
                        ),
                        "exit_signal_at": pending_exit[
                            "signal_at"
                        ],
                        "exit_at": label,
                        "exit_price": round(exit_fill, 6),
                        "exit_raw_open": round(raw_open, 6),
                        "quantity": int(position["quantity"]),
                        "gross_pnl": round(gross_pnl, 2),
                        "transaction_costs": round(
                            float(position["entry_cost"])
                            + exit_cost,
                            2,
                        ),
                        "net_pnl": round(net_pnl, 2),
                        "return_pct": round(
                            trade_return,
                            4,
                        ),
                        "holding_bars": (
                            index
                            - int(position["entry_bar_index"])
                        ),
                        "exit_reason": pending_exit[
                            "reason"
                        ],
                    }
                )
                position = None
                pending_exit = None

            if pending_entry is not None and position is None:
                entry_fill = self._fill_price(
                    raw_open,
                    side="BUY",
                    slippage_bps=slippage_bps,
                )
                per_share = entry_fill * (
                    1.0 + cost_bps / 10_000.0
                )
                quantity = int(cash // per_share)
                if quantity > 0:
                    entry_notional = quantity * entry_fill
                    entry_cost = self._transaction_cost(
                        entry_notional,
                        cost_bps=cost_bps,
                    )
                    cash -= entry_notional + entry_cost
                    total_transaction_costs += entry_cost
                    total_slippage_impact += (
                        quantity
                        * raw_open
                        * slippage_bps
                        / 10_000.0
                    )
                    position = {
                        "entry_signal_at": pending_entry[
                            "signal_at"
                        ],
                        "entry_at": label,
                        "entry_price": entry_fill,
                        "entry_raw_open": raw_open,
                        "entry_cost": entry_cost,
                        "quantity": quantity,
                        "entry_bar_index": index,
                    }
                pending_entry = None

            if position is not None:
                invested_bar_count += 1

            market_value = (
                int(position["quantity"]) * close
                if position is not None
                else 0.0
            )
            equity_curve.append(
                {
                    "date": label,
                    "equity": round(cash + market_value, 2),
                    "cash": round(cash, 2),
                    "market_value": round(
                        market_value,
                        2,
                    ),
                }
            )

            if index >= len(frame) - 1:
                continue

            rsi = self._finite(row.get("RSI"))
            proximity = self._ema_proximity_pct(row)

            if position is None and pending_entry is None:
                if (
                    self._is_cross_up(previous, row)
                    and rsi is not None
                    and rsi >= rsi_threshold
                    and proximity is not None
                    and proximity <= ema_proximity_pct
                ):
                    pending_entry = {
                        "signal_at": label,
                        "rsi": rsi,
                        "ema_proximity_pct": proximity,
                    }

            elif position is not None and pending_exit is None:
                cross_down = self._is_cross_down(
                    previous,
                    row,
                )
                rsi_exit = (
                    rsi is not None
                    and rsi < rsi_threshold
                )
                if cross_down or rsi_exit:
                    reason = (
                        "EMA20_CROSS_BELOW_EMA50"
                        if cross_down
                        else "RSI_BELOW_THRESHOLD"
                    )
                    pending_exit = {
                        "signal_at": label,
                        "reason": reason,
                    }

        if position is not None:
            final_label = self._date_label(frame.index[-1])
            raw_exit = float(last_close)
            exit_fill = self._fill_price(
                raw_exit,
                side="SELL",
                slippage_bps=slippage_bps,
            )
            exit_notional = (
                int(position["quantity"]) * exit_fill
            )
            exit_cost = self._transaction_cost(
                exit_notional,
                cost_bps=cost_bps,
            )
            cash += exit_notional - exit_cost
            total_transaction_costs += exit_cost
            total_slippage_impact += (
                int(position["quantity"])
                * raw_exit
                * slippage_bps
                / 10_000.0
            )
            gross_pnl = (
                exit_fill - float(position["entry_price"])
            ) * int(position["quantity"])
            net_pnl = (
                gross_pnl
                - float(position["entry_cost"])
                - exit_cost
            )
            basis = (
                float(position["entry_price"])
                * int(position["quantity"])
                + float(position["entry_cost"])
            )
            trades.append(
                {
                    "trade_number": len(trades) + 1,
                    "side": "LONG",
                    "entry_signal_at": position[
                        "entry_signal_at"
                    ],
                    "entry_at": position["entry_at"],
                    "entry_price": round(
                        float(position["entry_price"]),
                        6,
                    ),
                    "entry_raw_open": round(
                        float(position["entry_raw_open"]),
                        6,
                    ),
                    "exit_signal_at": final_label,
                    "exit_at": final_label,
                    "exit_price": round(exit_fill, 6),
                    "exit_raw_open": round(raw_exit, 6),
                    "quantity": int(position["quantity"]),
                    "gross_pnl": round(gross_pnl, 2),
                    "transaction_costs": round(
                        float(position["entry_cost"])
                        + exit_cost,
                        2,
                    ),
                    "net_pnl": round(net_pnl, 2),
                    "return_pct": round(
                        (
                            net_pnl * 100.0 / basis
                            if basis > 0
                            else 0.0
                        ),
                        4,
                    ),
                    "holding_bars": (
                        len(frame)
                        - 1
                        - int(position["entry_bar_index"])
                    ),
                    "exit_reason": "END_OF_TEST",
                }
            )
            position = None
            if equity_curve:
                equity_curve[-1] = {
                    "date": final_label,
                    "equity": round(cash, 2),
                    "cash": round(cash, 2),
                    "market_value": 0.0,
                }

        wins = [
            item for item in trades
            if float(item.get("net_pnl") or 0.0) > 0
        ]
        losses = [
            item for item in trades
            if float(item.get("net_pnl") or 0.0) <= 0
        ]
        net_profit = float(cash - capital)
        return_pct = net_profit * 100.0 / capital
        win_rate = (
            len(wins) * 100.0 / len(trades)
            if trades
            else 0.0
        )
        expectancy = (
            sum(float(item["net_pnl"]) for item in trades)
            / len(trades)
            if trades
            else 0.0
        )
        average_win = (
            sum(float(item["net_pnl"]) for item in wins)
            / len(wins)
            if wins
            else 0.0
        )
        average_loss = (
            sum(float(item["net_pnl"]) for item in losses)
            / len(losses)
            if losses
            else 0.0
        )
        buy_hold_return = (
            (last_close / first_open - 1.0) * 100.0
        )
        equity_values = [
            float(item["equity"])
            for item in equity_curve
        ]
        max_drawdown = MaxDrawdown().calculate(
            equity_values
        )
        sharpe = SharpeRatio().calculate(
            self._equity_returns(equity_curve),
            risk_free=0.0,
        )
        exposure_pct = (
            invested_bar_count * 100.0 / max(1, len(frame) - 1)
        )

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
            "position_sizing": "all_available_cash_integer_shares",
            "execution_model": "signal_close_fill_next_open",
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
