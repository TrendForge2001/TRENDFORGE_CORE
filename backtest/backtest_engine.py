"""Canonical event-driven TrendForge backtest engine.

The engine is deliberately strategy-agnostic. Strategy code supplies entry
and exit decisions from completed bars; the engine owns execution semantics,
position sizing, costs, slippage, trade accounting, equity tracking and core
performance metrics.

Execution model
---------------
- Signals are evaluated after a bar closes.
- Orders are filled at the next bar open.
- Long-only, single-position simulation.
- Integer-share sizing using available cash.
- Optional transaction costs and slippage.
- Any open position is force-closed on the final bar close by default.

This module never creates paper or broker orders.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping

import pandas as pd

from backtest.max_drawdown import MaxDrawdown
from backtest.sharpe_ratio import SharpeRatio


SignalRule = Callable[
    [pd.Series, pd.Series],
    Mapping[str, Any] | None,
]


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Execution and capital controls for one historical simulation."""

    initial_capital: float = 100_000.0
    cost_bps: float = 0.0
    slippage_bps: float = 0.0
    force_final_exit: bool = True


@dataclass(slots=True)
class BacktestResult:
    """Strategy-independent historical simulation output."""

    trades: list[dict[str, Any]]
    equity_curve: list[dict[str, Any]]
    metrics: dict[str, Any]


class BacktestEngine:
    """Deterministic next-bar-open long-only backtest engine."""

    ENGINE_VERSION = "R69.2-v1"
    EXECUTION_MODEL = "signal_close_fill_next_open"
    POSITION_SIZING = "all_available_cash_integer_shares"

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self._validate_config()

    @staticmethod
    def _finite(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _date_label(value: Any) -> str:
        try:
            return pd.Timestamp(value).isoformat()
        except Exception:
            return str(value)

    def _validate_config(self) -> None:
        capital = self._finite(self.config.initial_capital)
        if capital is None or capital <= 0:
            raise ValueError("initial_capital must be a positive finite number")

        for name, value in (
            ("cost_bps", self.config.cost_bps),
            ("slippage_bps", self.config.slippage_bps),
        ):
            number = self._finite(value)
            if number is None or not 0.0 <= number <= 1_000.0:
                raise ValueError(
                    f"{name} must be a finite number between 0 and 1000"
                )

    @classmethod
    def _fill_price(
        cls,
        raw_price: float,
        *,
        side: str,
        slippage_bps: float,
    ) -> float:
        rate = float(slippage_bps) / 10_000.0
        if str(side).upper() == "BUY":
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
    def _profit_factor(
        trades: list[dict[str, Any]],
    ) -> float | None:
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

    @staticmethod
    def _validate_frame(frame: pd.DataFrame) -> None:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError("Backtest frame must be a non-empty DataFrame")
        if len(frame) < 2:
            raise ValueError("Backtest requires at least two bars")
        missing = [
            column
            for column in ("open", "close")
            if column not in frame.columns
        ]
        if missing:
            raise ValueError(
                "Backtest frame missing required columns: "
                + ", ".join(missing)
            )

    @staticmethod
    def _decision(
        rule: SignalRule,
        previous: pd.Series,
        current: pd.Series,
    ) -> dict[str, Any] | None:
        value = rule(previous, current)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise TypeError(
                "Backtest signal rules must return a mapping or None"
            )
        return dict(value)

    def run(
        self,
        frame: pd.DataFrame,
        *,
        entry_rule: SignalRule,
        exit_rule: SignalRule,
    ) -> BacktestResult:
        """Run one historical simulation over an indicator-enriched frame."""

        self._validate_frame(frame)
        if not callable(entry_rule) or not callable(exit_rule):
            raise TypeError("entry_rule and exit_rule must be callable")

        capital = float(self.config.initial_capital)
        cost_bps = float(self.config.cost_bps)
        slippage_bps = float(self.config.slippage_bps)

        cash = capital
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
                raise ValueError(f"Invalid open price at {label}")
            if close is None or close <= 0:
                raise ValueError(f"Invalid close price at {label}")

            # Pending decisions were generated only after the previous bar
            # completed, so fills occur strictly at this bar's open.
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
                        "exit_signal_at": pending_exit["signal_at"],
                        "exit_at": label,
                        "exit_price": round(exit_fill, 6),
                        "exit_raw_open": round(raw_open, 6),
                        "quantity": int(position["quantity"]),
                        "gross_pnl": round(gross_pnl, 2),
                        "transaction_costs": round(
                            float(position["entry_cost"]) + exit_cost,
                            2,
                        ),
                        "net_pnl": round(net_pnl, 2),
                        "return_pct": round(trade_return, 4),
                        "holding_bars": (
                            index - int(position["entry_bar_index"])
                        ),
                        "exit_reason": pending_exit.get(
                            "reason",
                            "STRATEGY_EXIT",
                        ),
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
                        "entry_signal_at": pending_entry["signal_at"],
                        "entry_at": label,
                        "entry_price": entry_fill,
                        "entry_raw_open": raw_open,
                        "entry_cost": entry_cost,
                        "quantity": quantity,
                        "entry_bar_index": index,
                        "signal_metadata": {
                            key: value
                            for key, value in pending_entry.items()
                            if key != "signal_at"
                        },
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
                    "market_value": round(market_value, 2),
                }
            )

            # There is no next bar on which to execute a signal generated
            # from the final close, so do not create new pending decisions.
            if index >= len(frame) - 1:
                continue

            if position is None and pending_entry is None:
                entry = self._decision(entry_rule, previous, row)
                if entry is not None:
                    pending_entry = {
                        "signal_at": label,
                        **entry,
                    }

            elif position is not None and pending_exit is None:
                exit_decision = self._decision(exit_rule, previous, row)
                if exit_decision is not None:
                    pending_exit = {
                        "signal_at": label,
                        **exit_decision,
                    }

        if position is not None and self.config.force_final_exit:
            final_label = self._date_label(frame.index[-1])
            raw_exit = float(last_close)
            exit_fill = self._fill_price(
                raw_exit,
                side="SELL",
                slippage_bps=slippage_bps,
            )
            exit_notional = int(position["quantity"]) * exit_fill
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
                    "entry_signal_at": position["entry_signal_at"],
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
                        float(position["entry_cost"]) + exit_cost,
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
            item
            for item in trades
            if float(item.get("net_pnl") or 0.0) > 0
        ]
        losses = [
            item
            for item in trades
            if float(item.get("net_pnl") or 0.0) <= 0
        ]
        final_equity = (
            float(equity_curve[-1]["equity"])
            if equity_curve
            else float(cash)
        )
        net_profit = float(final_equity - capital)
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
            (float(last_close) / float(first_open) - 1.0) * 100.0
        )
        equity_values = [
            float(item["equity"])
            for item in equity_curve
        ]
        max_drawdown = MaxDrawdown().calculate(equity_values)
        sharpe = SharpeRatio().calculate(
            self._equity_returns(equity_curve),
            risk_free=0.0,
        )
        exposure_pct = (
            invested_bar_count
            * 100.0
            / max(1, len(frame) - 1)
        )

        metrics = {
            "initial_capital": round(capital, 2),
            "final_capital": round(final_equity, 2),
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

        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            metrics=metrics,
        )


__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "SignalRule",
]
