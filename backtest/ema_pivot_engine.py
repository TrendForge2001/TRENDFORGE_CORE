"""Historical next-candle triggers, staged exits and causal trailing stops.

OHLC ambiguity is resolved against the position: an active stop precedes profit
levels. A new breakeven stop can also be hit on the partial-profit candle.
Trailing updates become active on the next candle, never retroactively.
"""

import math

import pandas as pd

from scanner.ema_pivot_scanner import pivot_plan
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS, setup_indicators
from scanner.multi_strategy_engine import MultiStrategyEngine
from scanner.portfolio_policy import number


class EmaPivotBacktestEngine:
    VERSION = "ema-pivot-next-candle-partial-trailing-v1"

    def __init__(self, *, strategy_engine=None):
        self.strategies = strategy_engine or MultiStrategyEngine()

    def run(
        self,
        frames,
        *,
        strategy_id,
        mode,
        interval,
        cost_bps=12.0,
        slippage_bps=5.0,
        liquidity_confirmation=False,
        tick_size=0.05,
        short_borrow_available=False,
        initial_capital=100_000.0,
    ):
        from backtest.portfolio_engine import SharedPortfolioEngine

        setup = EMA_PIVOT_SETUPS[strategy_id]
        if setup.direction == -1 and not short_borrow_available:
            raise ValueError(
                "Short research backtests require an explicit available-borrow "
                "assumption; this is not a borrow check or broker order"
            )
        for value in (cost_bps, slippage_bps):
            if number(value) is None or not 0 <= value <= 1000:
                raise ValueError("Costs and slippage must be between 0 and 1000 bps")
        if number(tick_size) is None or not 0 < tick_size <= 100:
            raise ValueError("Invalid research tick size")
        if number(initial_capital) is None or initial_capital < 1000:
            raise ValueError("Invalid research capital")
        frames = SharedPortfolioEngine.align(frames)
        index = next(iter(frames.values())).index
        direction, rate, slip_rate = (
            setup.direction,
            cost_bps / 10000,
            slippage_bps / 10000,
        )
        reserve, deployment = initial_capital * 0.2, initial_capital * 0.8
        cash = float(initial_capital)
        positions, pending, pending_exits = {}, [], set()
        trades, allocations, fills, curve, rejected = [], [], [], [], []
        rejection_counts = {}
        total_costs, total_slip = 0.0, 0.0
        peak_positions, peak_deployed, minimum_cash = 0, 0.0, cash
        keys = setup_indicators(setup)

        def reject(symbol, stamp, reason):
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            if len(rejected) < 100:
                rejected.append(
                    {"symbol": symbol, "signal_at": stamp.isoformat(), "reason": reason}
                )

        def exit_fill(symbol, raw, stamp, reason, quantity=None):
            nonlocal cash, total_costs, total_slip, minimum_cash
            position = positions[symbol]
            qty = position["remaining_quantity"] if quantity is None else quantity
            fill = raw * (1 - direction * slip_rate)
            fee = qty * fill * rate
            gross = direction * (fill - position["entry_price"]) * qty
            entry_fee_share = position["entry_cost"] * qty / position["quantity"]
            cash += qty * position["entry_price"] + gross - fee
            total_costs += fee
            total_slip += qty * raw * slip_rate
            leg = {
                "symbol": symbol,
                "strategy_id": strategy_id,
                "side": position["side"],
                "entry_at": position["entry_at"],
                "exit_at": stamp.isoformat(),
                "quantity": qty,
                "entry_price": position["entry_price"],
                "exit_price": fill,
                "exit_reason": reason,
                "gross_pnl": gross,
                "transaction_costs": entry_fee_share + fee,
                "net_pnl": gross - entry_fee_share - fee,
            }
            position["exit_legs"].append(leg)
            fills.append(leg)
            position["remaining_quantity"] -= qty
            position["capital_committed"] = (
                position["remaining_quantity"] * position["entry_price"]
            )
            minimum_cash = min(minimum_cash, cash)
            if position["remaining_quantity"] == 0:
                positions.pop(symbol)
                legs = position["exit_legs"]
                trades.append(
                    {
                        **position,
                        "symbol": symbol,
                        "strategy_id": strategy_id,
                        "trade_number": len(trades) + 1,
                        "exit_at": stamp.isoformat(),
                        "exit_reason": reason,
                        "exit_price": sum(
                            leg["exit_price"] * leg["quantity"] for leg in legs
                        )
                        / position["quantity"],
                        "final_exit_price": fill,
                        "gross_pnl": sum(leg["gross_pnl"] for leg in legs),
                        "transaction_costs": sum(
                            leg["transaction_costs"] for leg in legs
                        ),
                        "net_pnl": sum(leg["net_pnl"] for leg in legs),
                    }
                )

        def observation(stamp, rows):
            market = sum(
                p["remaining_quantity"]
                * (
                    p["entry_price"]
                    + direction * (float(rows[s]["close"]) - p["entry_price"])
                )
                for s, p in positions.items()
            )
            committed = sum(p["capital_committed"] for p in positions.values())
            curve.append(
                {
                    "date": stamp.isoformat(),
                    "equity": cash + market,
                    "cash": cash,
                    "capital_committed": committed,
                    "market_value": market,
                    "open_positions": len(positions),
                }
            )

        observation(index[0], {s: frame.iloc[0] for s, frame in frames.items()})
        for offset in range(1, len(index)):
            stamp = index[offset]
            rows = {s: frame.iloc[offset] for s, frame in frames.items()}
            for symbol in list(positions):
                p, row = positions[symbol], rows[symbol]
                if (
                    mode == "intraday"
                    and pd.Timestamp(p["entry_at"]).date() != stamp.date()
                ):
                    raise ValueError("Missing intraday 15:00 square-off candle")
                if mode == "intraday" and stamp.hour >= 15:
                    if (stamp.hour, stamp.minute) != (15, 0):
                        raise ValueError("Missing intraday 15:00 square-off candle")
                    exit_fill(
                        symbol, float(row["open"]), stamp, "INTRADAY_SESSION_EXIT_1500"
                    )
                elif symbol in pending_exits:
                    # A gap through the resting stop is attributed to that stop.
                    stop_gap = direction * (float(row["open"]) - p["stoploss"]) <= 0
                    exit_fill(
                        symbol,
                        float(row["open"]),
                        stamp,
                        "STOP_GAP" if stop_gap else "STRATEGY_EXIT",
                    )
            pending_exits.clear()

            # Rank from known signal-candle scores and reserve budgets before
            # observing which trigger fills. Intrabar exit cash is not reused.
            available = max(
                0.0,
                min(
                    deployment
                    - sum(p["capital_committed"] for p in positions.values()),
                    cash - reserve,
                ),
            )
            ranked = sorted(
                (p for p in pending if p["symbol"] not in positions),
                key=lambda p: (-p["score"], p["symbol"]),
            )[: max(0, 3 - len(positions))]
            total_score = sum(p["score"] for p in ranked)
            open_equity = cash + sum(
                p["remaining_quantity"]
                * (
                    p["entry_price"]
                    + direction * (float(rows[s]["open"]) - p["entry_price"])
                )
                for s, p in positions.items()
            )
            for candidate in ranked:
                symbol = candidate["symbol"]
                row = rows[symbol]
                signal_at = pd.Timestamp(candidate["entry_signal_at"])
                if mode == "intraday" and (
                    stamp.weekday() >= 5
                    or stamp.date() != signal_at.date()
                    or (stamp - signal_at).total_seconds() != 900
                    or not (9, 30) <= (stamp.hour, stamp.minute) < (14, 45)
                ):
                    reject(symbol, stamp, "next_candle_outside_entry_session")
                    continue
                trigger = candidate["plan"]["entry_trigger"]
                if (
                    direction
                    * (float(row["high" if direction == 1 else "low"]) - trigger)
                    < -1e-9
                ):
                    reject(symbol, stamp, "next_candle_trigger_expired")
                    continue
                raw = (max if direction == 1 else min)(float(row["open"]), trigger)
                fill = raw * (1 + direction * slip_rate)
                plan = pivot_plan(
                    setup,
                    candidate["signal_row"],
                    mode=mode,
                    tick_size=tick_size,
                    entry=fill,
                )
                if not plan or not plan["pivot_room_sufficient"]:
                    reject(symbol, stamp, "gap_or_slippage_failed_pivot_room")
                    continue
                budget = available * candidate["score"] / total_score
                risk_budget = max(0.0, open_equity) * 0.005
                # Fees on both sides count towards planned risk, while actual
                # gaps can still lose more than the budget.
                planned_risk = (
                    plan["risk_per_share"] + fill * rate + plan["stoploss"] * rate
                )
                quantity = min(
                    math.floor(budget / (fill * (1 + rate))),
                    math.floor(risk_budget / planned_risk),
                )
                if quantity < 2:
                    reject(symbol, stamp, "risk_or_budget_cannot_support_partial_exit")
                    continue
                fee = quantity * fill * rate
                spent = quantity * fill + fee
                if cash - spent < reserve - 1e-7:
                    reject(symbol, stamp, "cash_reserve_required")
                    continue
                position = {
                    "entry_at": stamp.isoformat(),
                    "entry_signal_at": candidate["entry_signal_at"],
                    "entry_price": fill,
                    "entry_raw_price": raw,
                    "side": "LONG" if direction == 1 else "SHORT",
                    "quantity": quantity,
                    "remaining_quantity": quantity,
                    "entry_cost": fee,
                    "capital_committed": quantity * fill,
                    "allocation_budget": budget,
                    "weight_pct": candidate["score"] / total_score * 100,
                    "score": candidate["score"],
                    "stoploss": plan["stoploss"],
                    "initial_stoploss": plan["stoploss"],
                    "partial_target": plan["partial_target"],
                    "target": plan["target2"],
                    "risk_per_share": plan["risk_per_share"],
                    "reward_risk": plan["reward_risk"],
                    "risk_reward": plan["risk_reward"],
                    "risk_budget": risk_budget,
                    "planned_initial_risk": quantity * planned_risk,
                    "signal_atr": plan["signal_atr"],
                    "pivot_room_r": plan["pivot_room_r"],
                    "partial_taken": False,
                    "best_close": None,
                    "exit_legs": [],
                    "indicators": candidate["indicators"],
                    "technical_evidence": candidate["checks"],
                }
                positions[symbol] = position
                allocations.append({"symbol": symbol, **position, "exit_legs": []})
                cash -= spent
                total_costs += fee
                total_slip += quantity * raw * slip_rate
                minimum_cash = min(minimum_cash, cash)
                peak_positions = max(peak_positions, len(positions))
                peak_deployed = max(
                    peak_deployed,
                    sum(p["capital_committed"] for p in positions.values()),
                )
            pending = []

            for symbol in list(positions):
                row, p = rows[symbol], positions[symbol]
                adverse, favourable = (
                    float(row["low" if direction == 1 else "high"]),
                    float(row["high" if direction == 1 else "low"]),
                )
                if direction * (adverse - p["stoploss"]) <= 0:
                    raw = (min if direction == 1 else max)(
                        float(row["open"]), p["stoploss"]
                    )
                    # Entry was intrabar: never invent a pre-entry open fill.
                    if p["entry_at"] == stamp.isoformat():
                        raw = p["stoploss"]
                    exit_fill(symbol, raw, stamp, "PROTECTIVE_STOP")
                    continue
                if (
                    not p["partial_taken"]
                    and direction * (favourable - p["partial_target"]) >= 0
                ):
                    raw = (max if direction == 1 else min)(
                        float(row["open"]), p["partial_target"]
                    )
                    exit_fill(symbol, raw, stamp, "PARTIAL_PROFIT", p["quantity"] // 2)
                    p["partial_taken"] = True
                    if not setup.trailing:
                        p["stoploss"] = p["entry_price"]
                        if direction * (adverse - p["stoploss"]) <= 0:
                            exit_fill(
                                symbol,
                                p["stoploss"],
                                stamp,
                                "BREAKEVEN_STOP_AMBIGUOUS_BAR",
                            )
                            continue
                if (
                    p["target"] is not None
                    and direction * (favourable - p["target"]) >= 0
                ):
                    raw = (max if direction == 1 else min)(
                        float(row["open"]), p["target"]
                    )
                    exit_fill(symbol, raw, stamp, "FINAL_TARGET")
                    continue
                if setup.trailing:
                    close = float(row["close"])
                    p["best_close"] = (
                        close
                        if p["best_close"] is None
                        else (max if direction == 1 else min)(p["best_close"], close)
                    )
                    atr = number(row.get("ATR_WILDER_14"))
                    if atr is not None and atr > 0:
                        next_stop = p["best_close"] - direction * 3 * atr
                        p["stoploss"] = (max if direction == 1 else min)(
                            p["stoploss"], next_stop
                        )

            if offset == len(index) - 1:
                for symbol in list(positions):
                    exit_fill(
                        symbol, float(rows[symbol]["close"]), stamp, "END_OF_TEST"
                    )
            if (
                len(positions) > 3
                or sum(p["capital_committed"] for p in positions.values())
                > deployment + 1e-6
            ):
                raise RuntimeError("Research portfolio capital invariant failed")
            observation(stamp, rows)
            if offset == len(index) - 1:
                continue
            for symbol, frame in frames.items():
                evaluation = self.strategies.evaluate(
                    frame.iloc[offset - 1 : offset + 1],
                    mode=mode,
                    interval=interval,
                    strategy_ids=[strategy_id],
                    liquidity_confirmation=liquidity_confirmation,
                    tick_size=tick_size,
                )["evaluations"][0]
                if symbol in positions:
                    if evaluation.get("exit_triggered"):
                        pending_exits.add(symbol)
                elif evaluation.get("entry_state") == "ARMED":
                    pending.append(
                        {
                            "symbol": symbol,
                            "score": evaluation["score"],
                            "entry_signal_at": stamp.isoformat(),
                            "signal_row": rows[symbol],
                            "plan": evaluation["entry_plan"],
                            "checks": evaluation["checks"],
                            "indicators": {
                                key: number(rows[symbol].get(key)) for key in keys
                            },
                        }
                    )
        profits = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
        losses = sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
        peak, drawdown = initial_capital, 0.0
        for point in curve:
            peak = max(peak, point["equity"])
            drawdown = max(drawdown, (peak - point["equity"]) / peak * 100)
        return {
            "metrics": {
                "initial_capital": initial_capital,
                "final_capital": cash,
                "net_profit": cash - initial_capital,
                "return_pct": (cash / initial_capital - 1) * 100,
                "total_trades": len(trades),
                "win_rate": sum(t["net_pnl"] > 0 for t in trades) / len(trades) * 100
                if trades
                else 0,
                "profit_factor": profits / abs(losses)
                if losses
                else None
                if profits
                else 0,
                "max_drawdown_pct": drawdown,
                "transaction_costs": total_costs,
                "slippage_impact_estimate": total_slip,
                "deployment_limit": deployment,
                "cash_reserve": reserve,
                "max_positions": 3,
                "max_observed_positions": peak_positions,
                "max_capital_committed": peak_deployed,
                "minimum_cash": minimum_cash,
            },
            "trades": trades,
            "exit_fills": fills,
            "equity_curve": curve,
            "allocations": allocations,
            "rejection_counts": rejection_counts,
            "rejection_samples": rejected,
            "start_date": index[0].isoformat(),
            "end_date": index[-1].isoformat(),
            "bars": len(index),
        }
