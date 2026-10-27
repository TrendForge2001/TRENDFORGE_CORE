"""Shared-cash three-position simulation using completed-bar source signals."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
from scanner.portfolio_policy import (
    ACCOUNT_CAPITAL,
    CASH_RESERVE,
    DEPLOYMENT_LIMIT,
    MAX_POSITIONS,
    allocate_candidates,
    number,
    risk_details,
)
from scanner.strategy_registry import get_strategy


class SharedPortfolioEngine:
    VERSION = "shared-three-stock-v1"

    def __init__(self, *, strategy_engine=None):
        self.strategies = MultiStrategyBacktestEngine(strategy_engine=strategy_engine)

    @staticmethod
    def align(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        if not frames or len(frames) > 100:
            raise ValueError("Choose 1–100 portfolio stocks")
        normalized = {}
        for symbol, frame in frames.items():
            if not isinstance(frame, pd.DataFrame) or len(frame) < 2:
                raise ValueError("Every portfolio stock needs completed candles")
            # Normalize index/replace OHLC columns without duplicating the wide
            # indicator matrix for every stock in a large candidate universe.
            frame = frame.copy(deep=False)
            if pd.api.types.is_numeric_dtype(frame.index.dtype):
                raise ValueError("Portfolio candles need timestamps")
            index = pd.DatetimeIndex(frame.index)
            if index.hasnans or index.has_duplicates:
                raise ValueError("Invalid or duplicate portfolio candle timestamps")
            frame.index = (
                index.tz_localize("Asia/Kolkata")
                if index.tz is None
                else index.tz_convert("Asia/Kolkata")
            )
            frame = frame.sort_index()
            for key in ("open", "high", "low", "close"):
                if key not in frame:
                    raise ValueError("Invalid portfolio OHLC values")
                frame[key] = pd.to_numeric(frame[key], errors="coerce")
                if any(number(x) is None or x <= 0 for x in frame[key]):
                    raise ValueError("Invalid portfolio OHLC values")
            if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any() or (
                frame["low"] > frame[["open", "close", "high"]].min(axis=1)
            ).any():
                raise ValueError("Inconsistent portfolio OHLC values")
            normalized[symbol] = frame
        start = max(frame.index[0] for frame in normalized.values())
        end = min(frame.index[-1] for frame in normalized.values())
        aligned = {s: f.loc[start:end] for s, f in normalized.items()}
        reference = next(iter(aligned.values())).index
        if len(reference) < 2 or any(
            not f.index.equals(reference) for f in aligned.values()
        ):
            raise ValueError(
                "Stocks need aligned candle coverage; narrow the universe or period"
            )
        return aligned

    def run(
        self,
        frames: dict[str, pd.DataFrame],
        *,
        strategy_id: str,
        mode: str,
        interval: str,
        cost_bps: float = 12.0,
        slippage_bps: float = 5.0,
    ) -> dict[str, Any]:
        definition = self.strategies.validate_strategy(strategy_id, mode=mode)
        if interval not in definition["intervals"]:
            raise ValueError("Portfolio strategy interval mismatch")
        for value in (cost_bps, slippage_bps):
            if number(value) is None or not 0 <= value <= 1000:
                raise ValueError("Costs and slippage must be between 0 and 1000 bps")
        frames = self.align(frames)
        index = next(iter(frames.values())).index
        symbols = sorted(frames)
        cash = ACCOUNT_CAPITAL
        positions = {}
        pending_entries = []
        pending_exits = set()
        trades = []
        allocations = []
        fees = 0.0
        slip = 0.0
        peak_positions, peak_deployed, minimum_cash = 0, 0.0, ACCOUNT_CAPITAL
        curve = [
            {
                "date": index[0].isoformat(),
                "equity": cash,
                "cash": cash,
                "capital_committed": 0.0,
                "market_value": 0.0,
                "open_positions": 0,
            }
        ]
        rate, slippage = cost_bps / 10_000, slippage_bps / 10_000
        indicator_keys = (*get_strategy(strategy_id)["indicators"], "close", "volume")

        def close(symbol, raw, stamp, reason):
            nonlocal cash, fees, slip
            position = positions.pop(symbol)
            fill = raw * (1 - slippage)
            qty = position["quantity"]
            exit_fee = qty * fill * rate
            cash += qty * fill - exit_fee
            fees += exit_fee
            slip += qty * raw * slippage
            gross = (fill - position["entry_price"]) * qty
            trades.append(
                {
                    **position,
                    "trade_number": len(trades) + 1,
                    "symbol": symbol,
                    "strategy_id": strategy_id,
                    "exit_at": stamp.isoformat(),
                    "exit_price": fill,
                    "exit_reason": reason,
                    "gross_pnl": round(gross, 2),
                    "transaction_costs": round(position["entry_cost"] + exit_fee, 2),
                    "net_pnl": round(gross - position["entry_cost"] - exit_fee, 2),
                }
            )

        for offset in range(1, len(index)):
            stamp = index[offset]
            rows = {s: frames[s].iloc[offset] for s in symbols}
            # Known next-open exits precede entries. Intrabar exit proceeds must
            # not finance an entry at that same bar's earlier open.
            for symbol in list(positions):
                position = positions[symbol]
                if (
                    mode == "intraday"
                    and pd.Timestamp(position["entry_at"]).date() != stamp.date()
                ):
                    raise ValueError(
                        "Missing intraday square-off candle; "
                        "portfolio result unavailable"
                    )
                if (
                    mode == "intraday"
                    and stamp.hour >= 15
                    and (stamp.hour, stamp.minute) != (15, 0)
                ):
                    raise ValueError(
                        "Missing intraday square-off candle; "
                        "portfolio result unavailable"
                    )
                if symbol in pending_exits or (
                    mode == "intraday" and stamp.time().hour >= 15
                ):
                    reason = (
                        "STRATEGY_EXIT"
                        if symbol in pending_exits
                        else "INTRADAY_SESSION_EXIT_1500"
                    )
                    close(symbol, float(rows[symbol]["open"]), stamp, reason)
            pending_exits.clear()
            entry_window = mode != "intraday" or (
                stamp.weekday() < 5 and (9, 30) <= (stamp.hour, stamp.minute) < (14, 45)
            )
            candidates = []
            for candidate in pending_entries:
                if not entry_window or candidate["symbol"] in positions:
                    continue
                validated = allocate_candidates([candidate], budget=1, slots=1)
                if not validated:
                    continue
                candidate = validated[0]
                signal_at = pd.Timestamp(candidate["entry_signal_at"])
                if mode == "intraday" and (
                    stamp.date() != signal_at.date()
                    or (stamp - signal_at).total_seconds() != 900
                ):
                    continue
                raw = float(rows[candidate["symbol"]]["open"])
                fill = raw * (1 + slippage)
                distance = candidate["entry"] - candidate["stoploss"]
                if fill - distance <= 0:
                    continue
                candidates.append({**candidate, "raw_open": raw, "fill": fill})
            committed = math.fsum(p["capital_committed"] for p in positions.values())
            budget = max(0.0, min(DEPLOYMENT_LIMIT - committed, cash - CASH_RESERVE))
            selected = allocate_candidates(
                candidates, budget=budget, slots=MAX_POSITIONS - len(positions)
            )
            for candidate in selected:
                fill = candidate["fill"]
                quantity = math.floor(
                    candidate["allocation_budget"] / (fill * (1 + rate))
                )
                if quantity <= 0:
                    continue
                entry_cost = quantity * fill * rate
                spent = quantity * fill + entry_cost
                if (
                    spent > candidate["allocation_budget"]
                    or cash - spent < CASH_RESERVE
                ):
                    quantity -= 1
                    if quantity <= 0:
                        continue
                    entry_cost = quantity * fill * rate
                    spent = quantity * fill + entry_cost
                distance = candidate["entry"] - candidate["stoploss"]
                stop = fill - distance
                target = fill + candidate["reward_risk"] * distance
                position = {
                    "entry_at": stamp.isoformat(),
                    "entry_signal_at": candidate["entry_signal_at"],
                    "entry_price": fill,
                    "entry_raw_open": candidate["raw_open"],
                    "stoploss": stop,
                    "target": target,
                    "quantity": quantity,
                    "entry_cost": entry_cost,
                    "capital_committed": spent,
                    "allocation_budget": candidate["allocation_budget"],
                    "weight_pct": candidate["weight_pct"],
                    "score": candidate["score"],
                    "indicators": candidate["indicators"],
                    "technical_evidence": candidate["technical_evidence"],
                    **risk_details(fill, stop, target),
                }
                positions[candidate["symbol"]] = position
                position["gross_risk_amount"] = quantity * position["risk_per_share"]
                position["gross_reward_amount"] = (
                    quantity * position["reward_per_share"]
                )
                cash -= spent
                peak_positions = max(peak_positions, len(positions))
                peak_deployed = max(
                    peak_deployed,
                    sum(p["capital_committed"] for p in positions.values()),
                )
                minimum_cash = min(minimum_cash, cash)
                fees += entry_cost
                slip += quantity * candidate["raw_open"] * slippage
                allocations.append({"symbol": candidate["symbol"], **position})
            pending_entries = []
            for symbol in list(positions):
                row, position = rows[symbol], positions[symbol]
                hit_stop = row["low"] <= position["stoploss"]
                hit_target = row["high"] >= position["target"]
                if hit_stop:
                    close(
                        symbol,
                        min(float(row["open"]), position["stoploss"]),
                        stamp,
                        "ATR_STOP",
                    )
                elif hit_target:
                    close(
                        symbol,
                        max(float(row["open"]), position["target"]),
                        stamp,
                        "ATR_TARGET",
                    )
            if offset == len(index) - 1:
                for symbol in list(positions):
                    close(symbol, float(rows[symbol]["close"]), stamp, "END_OF_TEST")
            committed = math.fsum(p["capital_committed"] for p in positions.values())
            market_value = math.fsum(
                p["quantity"] * float(rows[s]["close"]) for s, p in positions.items()
            )
            if (
                cash < CASH_RESERVE - 1e-6
                or committed > DEPLOYMENT_LIMIT + 1e-6
                or len(positions) > MAX_POSITIONS
            ):
                raise RuntimeError("Portfolio capital invariant failed")
            curve.append(
                {
                    "date": stamp.isoformat(),
                    "equity": round(cash + market_value, 2),
                    "cash": round(cash, 2),
                    "capital_committed": round(committed, 2),
                    "market_value": round(market_value, 2),
                    "open_positions": len(positions),
                }
            )
            if offset == len(index) - 1:
                continue
            for symbol in symbols:
                current, previous = rows[symbol], frames[symbol].iloc[offset - 1]
                evaluation = self.strategies._evaluation(
                    previous,
                    current,
                    strategy_id=strategy_id,
                    mode=mode,
                    interval=interval,
                )
                if evaluation.get("status") != "evaluated":
                    continue
                if symbol in positions:
                    if evaluation.get("signal") == "EXIT":
                        pending_exits.add(symbol)
                    continue
                risk = evaluation.get("risk") or {}
                pending_entries.append(
                    {
                        "symbol": symbol,
                        "signal": evaluation.get("signal"),
                        "score": evaluation.get("score"),
                        **risk,
                        "entry_signal_at": stamp.isoformat(),
                        "indicators": {
                            key: number(current.get(key)) for key in indicator_keys
                        },
                        "technical_evidence": evaluation.get("checks") or {},
                    }
                )

        profits = math.fsum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
        losses = math.fsum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
        peak, drawdown = ACCOUNT_CAPITAL, 0.0
        for point in curve:
            peak = max(peak, point["equity"])
            drawdown = max(drawdown, (peak - point["equity"]) / peak * 100)
        metrics = {
            "initial_capital": ACCOUNT_CAPITAL,
            "final_capital": round(cash, 2),
            "net_profit": round(cash - ACCOUNT_CAPITAL, 2),
            "return_pct": (cash / ACCOUNT_CAPITAL - 1) * 100,
            "total_trades": len(trades),
            "win_rate": sum(t["net_pnl"] > 0 for t in trades) / len(trades) * 100
            if trades
            else 0.0,
            "profit_factor": profits / abs(losses)
            if losses
            else None
            if profits
            else 0.0,
            "max_drawdown_pct": drawdown,
            "transaction_costs": round(fees, 2),
            "slippage_impact_estimate": round(slip, 2),
            "deployment_limit": DEPLOYMENT_LIMIT,
            "cash_reserve": CASH_RESERVE,
            "max_positions": MAX_POSITIONS,
            "max_observed_positions": peak_positions,
            "max_capital_committed": round(peak_deployed, 2),
            "minimum_cash": round(minimum_cash, 2),
        }
        return {
            "metrics": metrics,
            "trades": trades,
            "equity_curve": curve,
            "allocations": allocations,
            "start_date": index[0].isoformat(),
            "end_date": index[-1].isoformat(),
            "bars": len(index),
        }
