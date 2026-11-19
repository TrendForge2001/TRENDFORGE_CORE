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
        admission_policy=None,
        signal_context=None,
        execution_sessions=None,
        evaluation_start=None,
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
        from services.paper_admission_policy import admit, fingerprint, validate

        policy = validate(admission_policy) if admission_policy is not None else None
        modeled_costs = policy["costs"][mode] if policy else None
        if policy:
            initial_capital = policy["capital"]
            cost_bps, slippage_bps = (
                modeled_costs["fee_bps"],
                modeled_costs["slippage_bps"],
            )
        sign = rules.direction(strategy_id, mode)
        if sign < 0 and not short_borrow_available and not policy:
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
        if policy and signal_context is None:
            if len(frames) != 1:
                raise ValueError("Aligned universe research requires the replay book")
            from services.aligned_signals import signals

            signal_context = signals(next(iter(frames.values())), mode)
        index = next(iter(frames.values())).index
        non_regular_sessions = 0
        if mode == "intraday":
            stamps = pd.DatetimeIndex(index)
            stamps = (
                stamps.tz_localize("Asia/Kolkata")
                if stamps.tz is None
                else stamps.tz_convert("Asia/Kolkata")
            )
            for day in set(stamps.date):
                day_stamps = stamps[stamps.date == day]
                # Approved entries exclude weekends and out-of-hours fills.
                # Keep those real prices as indicator evidence without demanding
                # a square-off event for a session that cannot open a position.
                # A missing 15:00 bar on any regular weekday remains an error.
                if day.weekday() >= 5 or not any(
                    (9, 15) <= (x.hour, x.minute) <= (15, 15) for x in day_stamps
                ):
                    non_regular_sessions += 1
                    continue
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
        day_entries, traded_days, delivery_charged = {}, set(), set()
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
                    dict(symbol=symbol, decision_at=stamp.isoformat(), reason=reason)
                )

        def close_position(symbol, raw, stamp, reason, quantity=None, limit=None):
            nonlocal cash, total_costs, total_slip, minimum_cash
            position = positions[symbol]
            if policy and mode != "intraday" and local(stamp).hour < 9:
                stamp = max(
                    local(stamp).normalize() + pd.Timedelta(hours=9, minutes=15),
                    pd.Timestamp(position["entry_at"]),
                )
            qty = position["remaining_quantity"] if quantity is None else quantity
            fill = float(raw) * (1 - sign * slip)
            if limit is not None:
                fill = max(fill, limit) if sign > 0 else min(fill, limit)
            fee = qty * fill * rate
            if policy and mode != "intraday" and sign > 0:
                day = local(stamp).date()
                charge_key = symbol, day
                if (
                    day > local(pd.Timestamp(position["entry_at"])).date()
                    and charge_key not in delivery_charged
                ):
                    fee += modeled_costs["overnight_delivery_exit_charge"]
                    delivery_charged.add(charge_key)
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

        if evaluation_start is None or index[0] >= evaluation_start:
            observe(index[0], previous)
        for offset in range(1, len(index)):
            stamp = index[offset]
            native = local(stamp)
            opening_stamp = (
                native.normalize() + pd.Timedelta(hours=9, minutes=15)
                if policy and mode != "intraday"
                else stamp
            )
            entry_stamp = (
                native.normalize() + pd.Timedelta(hours=9, minutes=30)
                if policy and mode != "intraday"
                else stamp
            )
            entry_ranges = {}
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
                        symbol,
                        rows[symbol]["open"],
                        opening_stamp,
                        "INTRADAY_SQUARE_OFF",
                    )
                elif rules.opening_exit(
                    previous[symbol], rows[symbol], positions[symbol]
                ):
                    close_position(
                        symbol, rows[symbol]["open"], opening_stamp, "RSI_GAP_OPEN_EXIT"
                    )
                elif symbol in pending_exits:
                    close_position(
                        symbol,
                        rows[symbol]["open"],
                        opening_stamp,
                        pending_exits[symbol],
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
                key=lambda c: (
                    (
                        -c.get("strong", False),
                        -c.get("consensus_count", 0),
                        -c.get("confidence", 0),
                        c["symbol"],
                    )
                    if policy
                    else (-c["score"], c["symbol"])
                ),
            )
            if not policy:
                ranked = ranked[: max(0, MAX_POSITIONS - len(positions))]
            total_score = sum(c["score"] for c in ranked)
            opening_equity = cash + sum(
                p["remaining_quantity"]
                * (
                    p["entry_price"]
                    + sign * (float(rows[s]["open"]) - p["entry_price"])
                )
                for s, p in positions.items()
            )
            opened_this_scan = 0
            for candidate in ranked:
                if evaluation_start is not None and stamp < evaluation_start:
                    continue
                if policy and sign < 0 and not short_borrow_available:
                    reject(
                        candidate["symbol"],
                        entry_stamp,
                        "short_availability_not_assumed",
                    )
                    continue
                if policy and opened_this_scan >= policy["max_entries_per_scan"]:
                    reject(
                        candidate["symbol"],
                        entry_stamp,
                        "maximum_entries_per_scan_reached",
                    )
                    continue
                symbol = candidate["symbol"]
                signal_stamp = local(pd.Timestamp(candidate["entry_signal_at"]))
                if mode == "intraday" and (
                    native.date() != signal_stamp.date()
                    or (native - signal_stamp).total_seconds() != 900
                    or not (9, 15) <= (native.hour, native.minute) < (15, 0)
                ):
                    reject(symbol, stamp, "next_native_open_unavailable")
                    continue
                execution_row = None
                if policy and mode != "intraday":
                    if (
                        execution_sessions is None
                        or native.normalize() not in execution_sessions.index
                    ):
                        reject(
                            symbol,
                            entry_stamp,
                            "observed_0930_execution_session_unavailable",
                        )
                        continue
                    execution_row = execution_sessions.loc[native.normalize()]
                raw = float(
                    execution_row["open"]
                    if execution_row is not None
                    else rows[symbol]["open"]
                )
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
                if policy:
                    legs = [leg for trade in trades for leg in trade["exit_legs"]] + [
                        leg for p in positions.values() for leg in p["exit_legs"]
                    ]
                    day = local(entry_stamp).date()
                    today = [
                        leg
                        for leg in legs
                        if local(pd.Timestamp(leg["exit_at"])).date() == day
                    ]
                    remaining_fees = sum(
                        p["entry_cost"] * p["remaining_quantity"] / p["quantity"]
                        for p in positions.values()
                    )
                    realized = sum(leg["net_pnl"] for leg in legs)
                    unrealized = (
                        sum(
                            sign
                            * (float(rows[s]["open"]) - p["entry_price"])
                            * p["remaining_quantity"]
                            for s, p in positions.items()
                        )
                        - remaining_fees
                    )
                    state = dict(
                        symbol_open=symbol in positions,
                        symbol_entered_today=(day, symbol) in traded_days,
                        open_positions=len(positions),
                        daily_entries=day_entries.get(day, 0),
                        daily_realized_loss=sum(
                            max(0, -leg["net_pnl"]) for leg in today
                        ),
                        daily_realized_pnl=sum(leg["net_pnl"] for leg in today),
                        unrealized_pnl=unrealized,
                        equity=capital + realized + unrealized,
                        realized_pnl=realized,
                        committed=sum(
                            p["capital_committed"] for p in positions.values()
                        ),
                        open_entry_fees=remaining_fees,
                    )
                    gate = admit(
                        policy,
                        plan=plan,
                        score=candidate["score"],
                        confidence=candidate["confidence"],
                        now=local(entry_stamp).to_pydatetime(),
                        state=state,
                    )
                    if not gate["approved"]:
                        for reason in gate["reasons"]:
                            reject(symbol, entry_stamp, reason)
                        continue
                    qty, risk_budget = gate["quantity"], gate["risk_budget"]
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
                    "entry_at": entry_stamp.isoformat(),
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
                    "planned_initial_risk": gate["planned_initial_risk"]
                    if policy
                    else qty * reference_risk,
                    "sizing_reference_is_conditional": not plan.get(
                        "stop_is_resting_order", False
                    ),
                    "stop_reference_history": [],
                    "exit_legs": [],
                    "indicators": candidate["signal_evidence"],
                    "technical_evidence": candidate["checks"],
                }
                positions[symbol] = position
                if policy:
                    day = local(entry_stamp).date()
                    traded_days.add((day, symbol))
                    day_entries[day] = day_entries.get(day, 0) + 1
                    opened_this_scan += 1
                    if execution_row is not None:
                        entry_ranges[symbol] = {
                            **rows[symbol],
                            "high": float(execution_row["high"]),
                            "low": float(execution_row["low"]),
                            "open": raw,
                        }
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
                position, row = (
                    positions[symbol],
                    entry_ranges.get(symbol, rows[symbol]),
                )
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
                    close_position(
                        symbol,
                        rows[symbol]["close"],
                        native.normalize() + pd.Timedelta(hours=15, minutes=30)
                        if policy and mode != "intraday"
                        else stamp,
                        "END_OF_TEST",
                    )
            if (
                len(positions) > MAX_POSITIONS
                or cash < -1e-6
                or sum(p["capital_committed"] for p in positions.values())
                > capital + 1e-6
            ):
                raise RuntimeError("Approved portfolio capital invariant failed")
            if evaluation_start is None or stamp >= evaluation_start:
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
                    signal = (signal_context or {}).get(stamp) if policy else None
                    evaluation = (
                        (signal or {}).get("evaluations", {}).get(strategy_id)
                        if policy and signal_context is not None
                        else self.entry_evaluation(
                            previous[symbol], row, context, strategy_id
                        )
                    )
                    if evaluation and evaluation["entry_state"] == "ARMED":
                        if policy and signal and signal["consensus"] == "CONFLICT":
                            reject(symbol, stamp, "scanner_consensus_conflict")
                            continue
                        pending.append(
                            dict(
                                symbol=symbol,
                                score=evaluation["score"],
                                entry_signal_at=stamp.isoformat(),
                                signal_row=row,
                                signal_evidence=rules.evidence(row),
                                checks=evaluation["checks"],
                                confidence=signal["consensus_score"]
                                if signal
                                else 80.0,
                                strong=bool(
                                    signal and signal["consensus"].startswith("STRONG_")
                                ),
                                consensus_count=signal["count"] if signal else 1,
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
                non_regular_sessions=non_regular_sessions,
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
                admission_policy_hash=fingerprint(policy) if policy else None,
                validation_basis="paper_policy_independent_stock"
                if policy
                else "native_independent_stock_research",
                cost_model=modeled_costs,
                rejection_counts=rejection_counts,
                rejection_samples=rejected,
                rejection_sample_limit=100,
            ),
            trades=trades,
            exit_fills=fills,
            equity_curve=curve,
            allocations=allocations,
            rejection_counts=rejection_counts,
            rejection_samples=rejected,
            start_date=(
                index[index >= evaluation_start][0]
                if evaluation_start is not None
                else index[0]
            ).isoformat(),
            end_date=index[-1].isoformat(),
            bars=int(sum(index >= evaluation_start))
            if evaluation_start is not None
            else len(index),
        )
