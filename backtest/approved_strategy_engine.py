"""Shared-cash simulator for the approved horizon rules.

Completed signals execute at the following native open. Conditional references
are never treated as price stops. Short collateral reserves the full notional;
short proceeds cannot fund another trade.
"""

import math

import pandas as pd

from backtest.indicator_rows import indicator_rows
from scanner import approved_strategies as rules
from scanner.portfolio_policy import MAX_POSITIONS, number


class ApprovedStrategyBacktestEngine:
    VERSION = rules.VERSION

    def __init__(self, *, strategy_engine=None):
        self.strategies = strategy_engine

    def entry_evaluation(self, previous, row, context, strategy_id):
        # Flat bars that fail a required entry condition cannot arm an order.
        # Avoid building/copying a complete execution plan on every such bar.
        if not all(
            rules.native_entry_checks(strategy_id, previous, row, context).values()
        ):
            return None
        return rules.evaluate(previous, row, context, strategy_id)

    def run(
        self,
        frames,
        *,
        strategy_id,
        mode,
        interval,
        initial_capital=100_000.0,
        cost_bps=12.0,
        slippage_bps=5.0,
        liquidity_confirmation=False,
        tick_size=0.05,
        short_borrow_available=False,
        progress=None,
        horizon=None,
    ):
        from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
        from backtest.portfolio_engine import SharedPortfolioEngine

        MultiStrategyBacktestEngine().validate_strategy(strategy_id, mode=mode)
        context = rules.context_for(
            strategy_id,
            mode,
            interval,
            horizon=horizon,
            tick_size=tick_size,
            liquidity_confirmation=liquidity_confirmation,
        )
        if rules.exit_only(strategy_id, mode):
            raise ValueError(
                "Outside intraday this strategy is an exit signal, not an entry "
                "strategy"
            )
        sign = rules.direction(strategy_id, mode)
        if sign < 0 and not short_borrow_available:
            raise ValueError(
                "Intraday paper short availability must be explicitly assumed"
            )
        costs, slippage, capital = map(
            number, (cost_bps, slippage_bps, initial_capital)
        )
        if (
            costs is None
            or slippage is None
            or not 0 <= costs <= 1000
            or not 0 <= slippage <= 1000
        ):
            raise ValueError("Costs and slippage must be between 0 and 1000 bps")
        if capital is None or capital < 1000:
            raise ValueError("Invalid backtest capital")
        frames = SharedPortfolioEngine.align(frames)
        index = next(iter(frames.values())).index
        if mode == "intraday":
            stamps = pd.DatetimeIndex(index)
            stamps = (
                stamps.tz_localize("Asia/Kolkata")
                if stamps.tz is None
                else stamps.tz_convert("Asia/Kolkata")
            )
            for day in set(stamps.date):
                day_stamps = stamps[stamps.date == day]
                if (
                    day != stamps[-1].date()
                    or (stamps[-1].hour, stamps[-1].minute) >= (15, 0)
                ) and not any((x.hour, x.minute) == (15, 0) for x in day_stamps):
                    raise ValueError(
                        "Intraday history is missing its 15:00 IST square-off candle"
                    )
        rate, slip = costs / 10000, slippage / 10000
        cash, total_costs, total_slip = capital, 0.0, 0.0
        positions, pending, pending_exits = {}, [], {}
        trades, fills, allocations, curve, rejected = [], [], [], [], []
        rejection_counts = {}
        peak_positions, peak_deployed, minimum_cash = 0, 0.0, capital
        iterators = {
            symbol: indicator_rows(frame, rules.KEYS)
            for symbol, frame in frames.items()
        }
        previous = {symbol: next(iterator) for symbol, iterator in iterators.items()}

        def local(stamp):
            return (
                stamp.tz_localize("Asia/Kolkata")
                if stamp.tzinfo is None
                else stamp.tz_convert("Asia/Kolkata")
            )

        def reject(symbol, stamp, reason):
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            if len(rejected) < 100:
                rejected.append(
                    dict(symbol=symbol, signal_at=stamp.isoformat(), reason=reason)
                )

        def close_position(symbol, raw, stamp, reason, quantity=None, limit=None):
            nonlocal cash, total_costs, total_slip, minimum_cash
            position = positions[symbol]
            qty = position["remaining_quantity"] if quantity is None else quantity
            fill = float(raw) * (1 - sign * slip)
            if limit is not None:
                fill = max(fill, limit) if sign > 0 else min(fill, limit)
            fee = qty * fill * rate
            gross = sign * (fill - position["entry_price"]) * qty
            entry_fee = position["entry_cost"] * qty / position["quantity"]
            cash += qty * position["entry_price"] + gross - fee
            total_costs += fee
            total_slip += qty * sign * (float(raw) - fill)
            leg = dict(
                symbol=symbol,
                strategy_id=strategy_id,
                side=position["side"],
                entry_at=position["entry_at"],
                exit_at=stamp.isoformat(),
                quantity=qty,
                entry_price=position["entry_price"],
                exit_price=fill,
                exit_reason=reason,
                gross_pnl=gross,
                transaction_costs=entry_fee + fee,
                net_pnl=gross - entry_fee - fee,
            )
            position["exit_legs"].append(leg)
            fills.append(leg)
            position["remaining_quantity"] -= qty
            position["capital_committed"] = (
                position["remaining_quantity"] * position["entry_price"]
            )
            minimum_cash = min(minimum_cash, cash)
            if not position["remaining_quantity"]:
                positions.pop(symbol)
                legs = position["exit_legs"]
                trades.append(
                    {
                        **position,
                        "symbol": symbol,
                        "trade_number": len(trades) + 1,
                        "exit_at": stamp.isoformat(),
                        "exit_reason": reason,
                        "exit_price": sum(x["exit_price"] * x["quantity"] for x in legs)
                        / position["quantity"],
                        "final_exit_price": fill,
                        **{
                            key: sum(x[key] for x in legs)
                            for key in ("gross_pnl", "transaction_costs", "net_pnl")
                        },
                    }
                )

        def observe(stamp, rows):
            market = sum(
                p["remaining_quantity"]
                * (
                    p["entry_price"]
                    + sign * (float(rows[s]["close"]) - p["entry_price"])
                )
                for s, p in positions.items()
            )
            curve.append(
                dict(
                    date=stamp.isoformat(),
                    equity=cash + market,
                    cash=cash,
                    capital_committed=sum(
                        p["capital_committed"] for p in positions.values()
                    ),
                    market_value=market,
                    open_positions=len(positions),
                )
            )

        observe(index[0], previous)
        for offset in range(1, len(index)):
            stamp = index[offset]
            native = local(stamp)
            rows = {symbol: next(iterator) for symbol, iterator in iterators.items()}
            if progress and (
                offset == 1 or offset % 10 == 0 or offset == len(index) - 1
            ):
                progress(offset, len(index) - 1)
            for symbol in list(positions):
                if mode == "intraday" and (
                    (native.hour, native.minute) >= (15, 0)
                    or local(pd.Timestamp(positions[symbol]["entry_at"])).date()
                    != native.date()
                ):
                    close_position(
                        symbol, rows[symbol]["open"], stamp, "INTRADAY_SQUARE_OFF"
                    )
                elif rules.opening_exit(
                    previous[symbol], rows[symbol], positions[symbol]
                ):
                    close_position(
                        symbol, rows[symbol]["open"], stamp, "RSI_GAP_OPEN_EXIT"
                    )
                elif symbol in pending_exits:
                    close_position(
                        symbol, rows[symbol]["open"], stamp, pending_exits[symbol]
                    )
            pending_exits.clear()
            available = max(
                0.0,
                min(
                    capital - sum(p["capital_committed"] for p in positions.values()),
                    cash,
                ),
            )
            ranked = sorted(
                (c for c in pending if c["symbol"] not in positions),
                key=lambda c: (-c["score"], c["symbol"]),
            )[: max(0, MAX_POSITIONS - len(positions))]
            total_score = sum(c["score"] for c in ranked)
            opening_equity = cash + sum(
                p["remaining_quantity"]
                * (
                    p["entry_price"]
                    + sign * (float(rows[s]["open"]) - p["entry_price"])
                )
                for s, p in positions.items()
            )
            for candidate in ranked:
                symbol = candidate["symbol"]
                signal_stamp = local(pd.Timestamp(candidate["entry_signal_at"]))
                if mode == "intraday" and (
                    native.date() != signal_stamp.date()
                    or (native - signal_stamp).total_seconds() != 900
                    or not (9, 15) <= (native.hour, native.minute) < (15, 0)
                ):
                    reject(symbol, stamp, "next_native_open_unavailable")
                    continue
                raw = float(rows[symbol]["open"])
                fill = raw * (1 + sign * slip)
                plan = rules.plan_for(
                    strategy_id, candidate["signal_row"], context, entry=fill
                )
                if not plan:
                    reject(
                        symbol, stamp, "actual_fill_failed_reference_or_target_ordering"
                    )
                    continue
                budget = available * candidate["score"] / total_score
                risk_budget = max(0.0, opening_equity) * 0.005
                reference_risk = (
                    plan["risk_per_share"] + (fill + plan["stoploss"]) * rate
                )
                qty = min(
                    math.floor(budget / (fill * (1 + rate))),
                    math.floor(risk_budget / reference_risk),
                )
                if qty < (2 if plan["annual"] else 1):
                    reject(symbol, stamp, "insufficient_reference_risk_or_cash_budget")
                    continue
                fee = qty * fill * rate
                spent = qty * fill + fee
                if spent > cash + 1e-7:
                    reject(symbol, stamp, "cash_budget_exceeded")
                    continue
                position = {
                    **plan,
                    "symbol": symbol,
                    "entry_at": stamp.isoformat(),
                    "entry_signal_at": candidate["entry_signal_at"],
                    "entry_price": fill,
                    "entry_raw_price": raw,
                    "quantity": qty,
                    "remaining_quantity": qty,
                    "entry_cost": fee,
                    "capital_committed": qty * fill,
                    "allocation_budget": budget,
                    "weight_pct": candidate["score"] / total_score * 100,
                    "score": candidate["score"],
                    "target": plan.get("target2"),
                    "risk_budget": risk_budget,
                    "planned_initial_risk": qty * reference_risk,
                    "sizing_reference_is_conditional": not plan.get(
                        "stop_is_resting_order", False
                    ),
                    "stop_reference_history": [],
                    "exit_legs": [],
                    "indicators": candidate["signal_evidence"],
                    "technical_evidence": candidate["checks"],
                }
                positions[symbol] = position
                allocations.append(
                    {**position, "exit_legs": [], "stop_reference_history": []}
                )
                cash -= spent
                total_costs += fee
                total_slip += qty * raw * slip
                minimum_cash = min(minimum_cash, cash)
                peak_positions = max(peak_positions, len(positions))
                peak_deployed = max(
                    peak_deployed,
                    sum(p["capital_committed"] for p in positions.values()),
                )
            pending = []
            for symbol in list(positions):
                position, row = positions[symbol], rows[symbol]
                stop = position["stoploss"]
                # Adverse price event wins when OHLC cannot establish order.
                adverse = float(row["low"] if sign > 0 else row["high"])
                if (
                    position.get("stop_is_resting_order")
                    and sign * (adverse - stop) <= 0
                ):
                    raw = (
                        min(float(row["open"]), stop)
                        if sign > 0
                        else max(float(row["open"]), stop)
                    )
                    close_position(symbol, raw, stamp, "STOPLOSS")
                    continue
                target = position.get("target")
                if (
                    position["annual"]
                    and not position["partial_taken"]
                    and row["high"] >= position["partial_target"]
                ):
                    close_position(
                        symbol,
                        max(float(row["open"]), position["partial_target"]),
                        stamp,
                        "R1_PARTIAL_PROFIT",
                        position["quantity"] // 2,
                        limit=position["partial_target"],
                    )
                    position["partial_taken"] = True
                favorable = float(row["high"] if sign > 0 else row["low"])
                if target is not None and sign * (favorable - target) >= 0:
                    raw = (
                        max(float(row["open"]), target)
                        if sign > 0
                        else min(float(row["open"]), target)
                    )
                    close_position(
                        symbol,
                        raw,
                        stamp,
                        "R3_FINAL_TARGET" if position["annual"] else "STRATEGY_TARGET",
                        limit=target,
                    )
            if offset == len(index) - 1:
                for symbol in list(positions):
                    close_position(symbol, rows[symbol]["close"], stamp, "END_OF_TEST")
            if (
                len(positions) > MAX_POSITIONS
                or cash < -1e-6
                or sum(p["capital_committed"] for p in positions.values())
                > capital + 1e-6
            ):
                raise RuntimeError("Approved portfolio capital invariant failed")
            observe(stamp, rows)
            if offset == len(index) - 1:
                continue
            for symbol, row in rows.items():
                if symbol in positions:
                    position = positions[symbol]
                    before = position["stoploss"]
                    reason = rules.closed_exit(previous[symbol], row, position, context)
                    if position["stoploss"] != before:
                        position["stop_reference_history"].append(
                            dict(
                                confirmed_at=stamp.isoformat(),
                                reference=position["stoploss"],
                            )
                        )
                    if reason:
                        pending_exits[symbol] = reason
                else:
                    evaluation = self.entry_evaluation(
                        previous[symbol], row, context, strategy_id
                    )
                    if evaluation and evaluation["entry_state"] == "ARMED":
                        pending.append(
                            dict(
                                symbol=symbol,
                                score=evaluation["score"],
                                entry_signal_at=stamp.isoformat(),
                                signal_row=row,
                                signal_evidence=rules.evidence(row),
                                checks=evaluation["checks"],
                            )
                        )
            previous = rows

        profits = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
        losses = sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
        peak, drawdown = capital, 0.0
        for point in curve:
            peak = max(peak, point["equity"])
            drawdown = max(drawdown, (peak - point["equity"]) / peak * 100)
        return dict(
            metrics=dict(
                initial_capital=capital,
                final_capital=cash,
                net_profit=cash - capital,
                return_pct=(cash / capital - 1) * 100,
                total_trades=len(trades),
                win_rate=sum(t["net_pnl"] > 0 for t in trades) / len(trades) * 100
                if trades
                else 0,
                profit_factor=profits / abs(losses)
                if losses
                else None
                if profits
                else 0,
                max_drawdown_pct=drawdown,
                transaction_costs=total_costs,
                slippage_impact_estimate=total_slip,
                deployment_limit=capital,
                cash_reserve=0.0,
                max_positions=MAX_POSITIONS,
                max_observed_positions=peak_positions,
                max_capital_committed=peak_deployed,
                minimum_cash=minimum_cash,
            ),
            trades=trades,
            exit_fills=fills,
            equity_curve=curve,
            allocations=allocations,
            rejection_counts=rejection_counts,
            rejection_samples=rejected,
            start_date=index[0].isoformat(),
            end_date=index[-1].isoformat(),
            bars=len(index),
        )
