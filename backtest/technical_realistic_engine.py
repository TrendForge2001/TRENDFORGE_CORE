"""R71.5 technical backtest engine with bracket-risk execution realism.

Signals remain completed-bar decisions. Entries and ordinary technical exits
fill at the next bar open. ATR stop/target levels are fixed using information
known at the entry signal and are then evaluated against subsequent OHLC bars.
For a bar that touches both stop and target, the default is conservative:
the stop is assumed to execute first. Intraday positions are force-exited at
15:00 IST and never carried overnight.

This module is historical simulation only and never creates paper/broker orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
import math
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.max_drawdown import MaxDrawdown
from backtest.sharpe_ratio import SharpeRatio


SignalRule = Callable[[pd.Series, pd.Series], Mapping[str, Any] | None]


@dataclass(frozen=True, slots=True)
class TechnicalRealisticConfig:
    initial_capital: float = 100_000.0
    cost_bps: float = 0.0
    slippage_bps: float = 0.0
    force_final_exit: bool = True
    same_bar_priority: str = "stop"
    intraday_exit_hour: int = 15
    intraday_exit_minute: int = 0


@dataclass(slots=True)
class TechnicalRealisticResult:
    trades: list[dict[str, Any]]
    equity_curve: list[dict[str, Any]]
    metrics: dict[str, Any]


class TechnicalRealisticBacktestEngine:
    ENGINE_VERSION = "R72.5.3-v1"
    EXECUTION_MODEL = (
        "signal_close_next_open_with_atr_brackets_and_intraday_1500_exit"
    )
    POSITION_SIZING = "all_available_cash_integer_shares"
    MARKET_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(self, config: TechnicalRealisticConfig | None = None) -> None:
        self.config = config or TechnicalRealisticConfig()
        self._validate_config()

    @staticmethod
    def _finite(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _label(value: Any) -> str:
        try:
            return pd.Timestamp(value).isoformat()
        except Exception:
            return str(value)

    @classmethod
    def _ist_stamp(cls, value: Any) -> pd.Timestamp | None:
        try:
            stamp = pd.Timestamp(value)
        except Exception:
            return None
        if pd.isna(stamp):
            return None
        try:
            if stamp.tzinfo is None:
                return stamp.tz_localize(cls.MARKET_TZ)
            return stamp.tz_convert(cls.MARKET_TZ)
        except Exception:
            return stamp

    def _validate_config(self) -> None:
        capital = self._finite(self.config.initial_capital)
        if capital is None or capital <= 0:
            raise ValueError("initial_capital must be positive")
        for name, value in (
            ("cost_bps", self.config.cost_bps),
            ("slippage_bps", self.config.slippage_bps),
        ):
            number = self._finite(value)
            if number is None or not 0 <= number <= 1000:
                raise ValueError(f"{name} must be between 0 and 1000")
        if self.config.same_bar_priority not in {"stop", "target"}:
            raise ValueError("same_bar_priority must be stop or target")

    @classmethod
    def _fill(cls, raw_price: float, *, side: str, slippage_bps: float) -> float:
        rate = float(slippage_bps) / 10_000.0
        return (
            float(raw_price) * (1.0 + rate)
            if side.upper() == "BUY"
            else float(raw_price) * (1.0 - rate)
        )

    @staticmethod
    def _cost(notional: float, *, cost_bps: float) -> float:
        return float(notional) * float(cost_bps) / 10_000.0

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
            raise TypeError("signal rules must return a mapping or None")
        return dict(value)

    @staticmethod
    def _validate_frame(frame: pd.DataFrame) -> None:
        if not isinstance(frame, pd.DataFrame) or frame.empty or len(frame) < 2:
            raise ValueError("backtest requires at least two OHLC bars")
        missing = [
            col for col in ("open", "high", "low", "close")
            if col not in frame.columns
        ]
        if missing:
            raise ValueError("backtest frame missing: " + ", ".join(missing))

    def _is_session_exit(self, value: Any, mode: str) -> bool:
        if str(mode).lower() != "intraday":
            return False
        stamp = self._ist_stamp(value)
        if stamp is None:
            return False
        cutoff = time(
            int(self.config.intraday_exit_hour),
            int(self.config.intraday_exit_minute),
        )
        return stamp.time() >= cutoff

    @staticmethod
    def _profit_factor(trades: list[dict[str, Any]]) -> float | None:
        gross_profit = sum(
            max(0.0, float(t.get("net_pnl") or 0.0)) for t in trades
        )
        gross_loss = abs(
            sum(min(0.0, float(t.get("net_pnl") or 0.0)) for t in trades)
        )
        if gross_loss > 0:
            return round(gross_profit / gross_loss, 4)
        return None if gross_profit > 0 else 0.0

    @staticmethod
    def _equity_returns(curve: list[dict[str, Any]]) -> list[float]:
        values = [float(x["equity"]) for x in curve if x.get("equity") is not None]
        return [
            current / previous - 1.0
            for previous, current in zip(values, values[1:])
            if previous > 0
        ]

    def run(
        self,
        frame: pd.DataFrame,
        *,
        entry_rule: SignalRule,
        exit_rule: SignalRule,
        mode: str,
    ) -> TechnicalRealisticResult:
        self._validate_frame(frame)
        mode = str(mode or "").lower()
        if mode not in {"intraday", "swing", "positional"}:
            raise ValueError("mode must be intraday, swing or positional")

        capital = float(self.config.initial_capital)
        cost_bps = float(self.config.cost_bps)
        slippage_bps = float(self.config.slippage_bps)
        cash = capital
        position: dict[str, Any] | None = None
        pending_entry: dict[str, Any] | None = None
        pending_exit: dict[str, Any] | None = None
        trades: list[dict[str, Any]] = []
        curve: list[dict[str, Any]] = []
        invested_bars = 0
        total_costs = 0.0
        total_slippage = 0.0

        first_open = self._finite(frame.iloc[0].get("open"))
        last_close = self._finite(frame.iloc[-1].get("close"))
        if first_open is None or first_open <= 0 or last_close is None or last_close <= 0:
            raise ValueError("invalid first open or final close")

        def close_position(
            *,
            raw_exit: float,
            exit_at: Any,
            reason: str,
            exit_signal_at: Any | None = None,
        ) -> None:
            nonlocal cash, position, total_costs, total_slippage
            assert position is not None
            fill = self._fill(
                raw_exit,
                side="SELL",
                slippage_bps=slippage_bps,
            )
            quantity = int(position["quantity"])
            exit_notional = quantity * fill
            exit_cost = self._cost(exit_notional, cost_bps=cost_bps)
            cash += exit_notional - exit_cost
            total_costs += exit_cost
            total_slippage += quantity * raw_exit * slippage_bps / 10_000.0
            gross = (fill - float(position["entry_price"])) * quantity
            net = gross - float(position["entry_cost"]) - exit_cost
            basis = (
                float(position["entry_price"]) * quantity
                + float(position["entry_cost"])
            )
            trades.append(
                {
                    "trade_number": len(trades) + 1,
                    "side": "LONG",
                    "entry_signal_at": position["entry_signal_at"],
                    "entry_at": position["entry_at"],
                    "entry_price": round(float(position["entry_price"]), 6),
                    "entry_raw_open": round(float(position["entry_raw_open"]), 6),
                    "stoploss": round(float(position["stoploss"]), 6),
                    "target": round(float(position["target"]), 6),
                    "exit_signal_at": (
                        self._label(exit_signal_at)
                        if exit_signal_at is not None
                        else None
                    ),
                    "exit_at": self._label(exit_at),
                    "exit_price": round(fill, 6),
                    "exit_raw_price": round(float(raw_exit), 6),
                    "quantity": quantity,
                    "gross_pnl": round(gross, 2),
                    "transaction_costs": round(
                        float(position["entry_cost"]) + exit_cost,
                        2,
                    ),
                    "net_pnl": round(net, 2),
                    "return_pct": round(net * 100.0 / basis if basis else 0.0, 4),
                    "holding_bars": int(
                        position.get("bars_held", 0)
                    ),
                    "exit_reason": reason,
                }
            )
            position = None

        for index in range(1, len(frame)):
            row = frame.iloc[index]
            previous = frame.iloc[index - 1]
            stamp = frame.index[index]
            label = self._label(stamp)
            raw_open = self._finite(row.get("open"))
            high = self._finite(row.get("high"))
            low = self._finite(row.get("low"))
            close = self._finite(row.get("close"))
            if any(v is None or v <= 0 for v in (raw_open, high, low, close)):
                raise ValueError(f"invalid OHLC at {label}")

            session_exit = self._is_session_exit(stamp, mode)

            if pending_exit is not None and position is not None:
                close_position(
                    raw_exit=float(raw_open),
                    exit_at=stamp,
                    reason=str(pending_exit.get("reason") or "TECHNICAL_EXIT"),
                    exit_signal_at=pending_exit.get("signal_at"),
                )
                pending_exit = None

            if position is not None and session_exit:
                close_position(
                    raw_exit=float(raw_open),
                    exit_at=stamp,
                    reason="INTRADAY_SESSION_EXIT_1500",
                )
                pending_exit = None

            if (
                pending_entry is not None
                and position is None
                and session_exit
                and mode == "intraday"
            ):
                # Never carry an unfilled intraday signal across the 15:00
                # session boundary into the next trading day.
                pending_entry = None

            if (
                pending_entry is not None
                and position is None
                and not session_exit
            ):
                entry_fill = self._fill(
                    float(raw_open),
                    side="BUY",
                    slippage_bps=slippage_bps,
                )
                signal_entry = self._finite(pending_entry.get("entry"))
                signal_stop = self._finite(pending_entry.get("stoploss"))
                reward_risk = self._finite(pending_entry.get("reward_risk")) or 2.0
                risk_distance = (
                    float(signal_entry) - float(signal_stop)
                    if signal_entry is not None
                    and signal_stop is not None
                    and signal_entry > signal_stop
                    else None
                )
                if risk_distance is not None and risk_distance > 0:
                    stoploss = max(0.01, entry_fill - risk_distance)
                    target = entry_fill + reward_risk * risk_distance
                    affordable = int(
                        cash / (
                            entry_fill
                            * (1.0 + cost_bps / 10_000.0)
                        )
                    )
                    if affordable > 0:
                        entry_notional = affordable * entry_fill
                        entry_cost = self._cost(
                            entry_notional,
                            cost_bps=cost_bps,
                        )
                        cash -= entry_notional + entry_cost
                        total_costs += entry_cost
                        total_slippage += (
                            affordable
                            * float(raw_open)
                            * slippage_bps
                            / 10_000.0
                        )
                        position = {
                            "entry_signal_at": pending_entry["signal_at"],
                            "entry_at": label,
                            "entry_price": entry_fill,
                            "entry_raw_open": float(raw_open),
                            "entry_cost": entry_cost,
                            "quantity": affordable,
                            "stoploss": stoploss,
                            "target": target,
                            "bars_held": 0,
                        }
                pending_entry = None

            if position is not None:
                position["bars_held"] = int(position.get("bars_held", 0)) + 1
                invested_bars += 1
                stoploss = float(position["stoploss"])
                target = float(position["target"])
                hit_stop = float(low) <= stoploss
                hit_target = float(high) >= target
                if hit_stop or hit_target:
                    choose_stop = hit_stop and (
                        not hit_target
                        or self.config.same_bar_priority == "stop"
                    )
                    if choose_stop:
                        raw_exit = min(float(raw_open), stoploss)
                        reason = (
                            "ATR_STOP_GAP"
                            if float(raw_open) < stoploss
                            else "ATR_STOP"
                        )
                    else:
                        raw_exit = max(float(raw_open), target)
                        reason = (
                            "ATR_TARGET_GAP"
                            if float(raw_open) > target
                            else "ATR_TARGET"
                        )
                    close_position(
                        raw_exit=raw_exit,
                        exit_at=stamp,
                        reason=reason,
                    )
                    pending_exit = None

            market_value = (
                int(position["quantity"]) * float(close)
                if position is not None
                else 0.0
            )
            curve.append(
                {
                    "date": label,
                    "equity": round(cash + market_value, 2),
                    "cash": round(cash, 2),
                    "market_value": round(market_value, 2),
                }
            )

            if index >= len(frame) - 1:
                continue

            if position is None and pending_entry is None and not session_exit:
                decision = self._decision(entry_rule, previous, row)
                if decision is not None:
                    pending_entry = {"signal_at": label, **decision}
            elif position is not None and pending_exit is None:
                decision = self._decision(exit_rule, previous, row)
                if decision is not None:
                    pending_exit = {"signal_at": label, **decision}

        if position is not None and self.config.force_final_exit:
            close_position(
                raw_exit=float(last_close),
                exit_at=frame.index[-1],
                reason="END_OF_TEST",
            )
            if curve:
                curve[-1] = {
                    "date": self._label(frame.index[-1]),
                    "equity": round(cash, 2),
                    "cash": round(cash, 2),
                    "market_value": 0.0,
                }

        final_equity = float(curve[-1]["equity"]) if curve else float(cash)
        net_profit = final_equity - capital
        wins = [t for t in trades if float(t.get("net_pnl") or 0) > 0]
        losses = [t for t in trades if float(t.get("net_pnl") or 0) <= 0]
        equity_values = [float(x["equity"]) for x in curve]
        max_dd = MaxDrawdown().calculate(equity_values) if equity_values else 0.0
        sharpe = SharpeRatio().calculate(self._equity_returns(curve), risk_free=0.0)
        metrics = {
            "initial_capital": round(capital, 2),
            "final_capital": round(final_equity, 2),
            "net_profit": round(net_profit, 2),
            "return_pct": round(net_profit * 100.0 / capital, 4),
            "buy_hold_return_pct": round(
                (float(last_close) / float(first_open) - 1.0) * 100.0,
                4,
            ),
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) * 100.0 / len(trades), 4) if trades else 0.0,
            "average_win": round(
                sum(float(t["net_pnl"]) for t in wins) / len(wins),
                2,
            ) if wins else 0.0,
            "average_loss": round(
                sum(float(t["net_pnl"]) for t in losses) / len(losses),
                2,
            ) if losses else 0.0,
            "expectancy": round(
                sum(float(t["net_pnl"]) for t in trades) / len(trades),
                2,
            ) if trades else 0.0,
            "profit_factor": self._profit_factor(trades),
            "max_drawdown_pct": round(float(max_dd), 4),
            "sharpe_ratio": round(float(sharpe), 4),
            "exposure_pct": round(
                invested_bars * 100.0 / max(1, len(frame) - 1),
                4,
            ),
            "transaction_costs": round(total_costs, 2),
            "slippage_impact_estimate": round(total_slippage, 2),
            "atr_stop_exits": sum(
                1 for t in trades if str(t.get("exit_reason", "")).startswith("ATR_STOP")
            ),
            "atr_target_exits": sum(
                1 for t in trades if str(t.get("exit_reason", "")).startswith("ATR_TARGET")
            ),
            "session_exits": sum(
                1 for t in trades if t.get("exit_reason") == "INTRADAY_SESSION_EXIT_1500"
            ),
        }
        metrics["excess_vs_buy_hold_pct"] = round(
            float(metrics["return_pct"]) - float(metrics["buy_hold_return_pct"]),
            4,
        )
        return TechnicalRealisticResult(
            trades=trades,
            equity_curve=curve,
            metrics=metrics,
        )


__all__ = [
    "SignalRule",
    "TechnicalRealisticBacktestEngine",
    "TechnicalRealisticConfig",
    "TechnicalRealisticResult",
]
