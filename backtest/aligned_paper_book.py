"""One shared research account on observed 15-minute prices; no order APIs.

Native daily/15-minute decisions and ranking are causal. This models a fixed
15-minute observation grid, not the exact live worker's quote/poll latency.
"""

from collections import Counter

import pandas as pd

from scanner import approved_strategies as rules
from scanner.strategy_registry import list_strategies
from services import execution_costs
from services.paper_admission_policy import admit, fingerprint, validate


def run_shared_book(
    store, *, symbols, policy, as_of, assume_short_borrow=False, progress=None
):
    from services.research_history import cutoff

    policy = validate(policy)
    if policy["capital"] != 100_000:
        raise ValueError("The requested shared research book requires ₹100,000 capital")
    start = cutoff(as_of, "60d")
    timeline = store.calendar(symbols)
    timeline = timeline[
        (timeline >= start) & (timeline + pd.Timedelta(minutes=15) <= as_of)
    ]
    if timeline.empty:
        raise ValueError("No completed execution bars in the common research window")
    mode_order = ("intraday", "swing", "positional")
    strategy_order = {
        mode: [
            r["strategy_id"]
            for r in list_strategies(mode=mode)
            if r["strategy_id"] in rules.APPROVED_IDS
            and not rules.exit_only(r["strategy_id"], mode)
        ]
        for mode in mode_order
    }
    symbol_order = {symbol: offset for offset, symbol in enumerate(symbols)}
    coverage = store.coverage(symbols)
    complete_daily_inputs = all(store.path("native_day", s).exists() for s in symbols)
    complete_quote_bars = sum(
        coverage[stamp.as_unit("ns").value] == len(symbols) for stamp in timeline
    )
    positions, trades, fills, curve = {}, [], [], []
    cash = policy["capital"]
    realized, committed = 0.0, 0.0
    daily_net, daily_loss, daily_entries = Counter(), Counter(), Counter()
    entered_days, dp_charged = set(), set()
    rejects = Counter()
    max_positions, minimum_cash = 0, cash
    processed_native = {}
    active_daily = {}
    previous_marks = {}

    def quote(symbol, stamp):
        frame = store.quote_frame(symbol)
        return frame.loc[stamp] if frame is not None and stamp in frame.index else None

    def native_pair(symbol, mode, stamp):
        frame = store.frame(
            "native_intra" if mode == "intraday" else "native_day", symbol
        )
        cut = stamp if mode == "intraday" else stamp.normalize()
        offset = int(frame.index.searchsorted(cut)) - 1
        return (
            (frame.iloc[offset - 1], frame.iloc[offset])
            if offset >= 1
            else (None, None)
        )

    def close(symbol, raw, stamp, reason, qty=None, limit=None):
        nonlocal cash, realized, committed
        p = positions[symbol]
        quantity = p["remaining_quantity"] if qty is None else qty
        day = stamp.date()
        costs = policy["costs"][p["mode"]]
        charge = 0.0
        if (
            p["direction"] > 0
            and p["mode"] != "intraday"
            and day > pd.Timestamp(p["entry_at"]).date()
            and (symbol, day) not in dp_charged
        ):
            charge = costs["overnight_delivery_exit_charge"]
            dp_charged.add((symbol, day))
        economic = execution_costs.exit_economics(
            p["entry_price"],
            raw,
            quantity,
            p["direction"],
            costs,
            entry_raw=p["entry_raw_price"],
            limit=limit,
            delivery_charge=charge,
        )
        cash += (
            quantity * p["entry_price"]
            + economic["gross_pnl"]
            - execution_costs.fee(economic["exit_price"], quantity, costs)
            - charge
        )
        committed -= quantity * p["entry_price"]
        realized += economic["net_pnl"]
        daily_net[day] += economic["net_pnl"]
        daily_loss[day] += max(0.0, -economic["net_pnl"])
        leg = dict(
            symbol=symbol,
            strategy_id=p["strategy_id"],
            mode=p["mode"],
            side=p["side"],
            entry_at=p["entry_at"],
            exit_at=stamp.isoformat(),
            exit_reason=reason,
            quantity=quantity,
            **economic,
        )
        p["exit_legs"].append(leg)
        fills.append(leg)
        p["remaining_quantity"] -= quantity
        if not p["remaining_quantity"]:
            trades.append(
                {
                    **p,
                    "exit_at": stamp.isoformat(),
                    "exit_reason": reason,
                    **{
                        key: sum(v[key] for v in p["exit_legs"])
                        for key in ("gross_pnl", "transaction_costs", "net_pnl")
                    },
                }
            )
            positions.pop(symbol)

    for offset, stamp in enumerate(timeline):
        if progress and offset % 25 == 0:
            progress(
                dict(
                    phase="shared_book", completed_bars=offset, total_bars=len(timeline)
                )
            )
        day = stamp.date()
        quotes = {}
        for symbol in list(positions):
            bar = quote(symbol, stamp)
            if bar is None:
                rejects["open_position_quote_unavailable"] += 1
                continue
            quotes[symbol] = bar
            p = positions[symbol]
            key = p["strategy_id"]
            if p["mode"] == "intraday" and (
                (stamp.hour, stamp.minute) >= (15, 0)
                or pd.Timestamp(p["entry_at"]).date() != day
            ):
                close(symbol, float(bar.open), stamp, "INTRADAY_SQUARE_OFF")
                continue
            previous, current = native_pair(symbol, p["mode"], stamp)
            if current is not None and processed_native.get(symbol) != current.name:
                if current.name.date() >= pd.Timestamp(p["entry_at"]).date():
                    context = rules.context_for(key, p["mode"])
                    reason = rules.closed_exit(previous, current, p, context)
                    if reason:
                        close(symbol, float(bar.open), stamp, reason)
                        continue
                processed_native[symbol] = current.name
            if (
                p.get("annual")
                and current is not None
                and active_daily.get(symbol) != day
            ):
                # Only today's opening field is used; current daily indicators
                # and close are still unknown at the first quote.
                daily = store.frame("native_day", symbol)
                opening = (
                    daily.loc[stamp.normalize(), "open"]
                    if stamp.normalize() in daily.index
                    else bar.open
                )
                if rules.opening_exit(current, {"open": opening}, p):
                    close(symbol, float(bar.open), stamp, "RSI_GAP_OPEN_EXIT")
                    continue
                active_daily[symbol] = day
        due = list(store.events(stamp))
        for mode in mode_order:
            source = [e for e in due if e["mode"] == mode]
            source.sort(
                key=lambda e: (
                    not e["consensus"].startswith("STRONG_"),
                    -e["count"],
                    -e["consensus_score"],
                    symbol_order[e["symbol"]],
                )
            )
            for key in strategy_order[mode]:
                opened_scan = 0
                for event in source:
                    if key not in event["strategy_ids"]:
                        continue
                    if opened_scan >= policy["max_entries_per_scan"]:
                        rejects["maximum_entries_per_scan_reached"] += 1
                        continue
                    symbol = event["symbol"]
                    # The live bridge requires a completely successful scan.
                    # Do not silently turn a degraded universe into an eligible
                    # shared account by dropping instruments with missing data.
                    if coverage[stamp.as_unit("ns").value] != len(symbols) or (
                        mode != "intraday" and not complete_daily_inputs
                    ):
                        rejects["scan_not_fully_completed"] += 1
                        continue
                    if event["consensus"] == "CONFLICT":
                        rejects["scanner_consensus_conflict"] += 1
                        continue
                    if rules.direction(key, mode) < 0 and not assume_short_borrow:
                        rejects["short_availability_not_assumed"] += 1
                        continue
                    bar = quote(symbol, stamp)
                    if bar is None:
                        rejects["observed_execution_quote_unavailable"] += 1
                        continue
                    if (
                        mode == "intraday"
                        and (stamp - event["stamp"]).total_seconds() != 900
                    ):
                        rejects["next_native_open_unavailable"] += 1
                        continue
                    sign = rules.direction(key, mode)
                    costs = policy["costs"][mode]
                    price = execution_costs.fill(
                        float(bar.open), sign, costs, opening=True
                    )
                    signal = pd.Series(event["signal_row"], name=event["stamp"])
                    plan = rules.plan_for(
                        key, signal, rules.context_for(key, mode), entry=price
                    )
                    if not plan:
                        rejects["actual_fill_failed_reference_or_target_ordering"] += 1
                        continue
                    open_fees = sum(
                        p["remaining_quantity"]
                        * execution_costs.fee(
                            p["entry_price"], 1, policy["costs"][p["mode"]]
                        )
                        for p in positions.values()
                    )
                    unrealized = -open_fees
                    for held, p in positions.items():
                        mark = quote(held, stamp)
                        if mark is None:
                            unrealized += (
                                p["direction"]
                                * (
                                    previous_marks.get(held, p["entry_price"])
                                    - p["entry_price"]
                                )
                                * p["remaining_quantity"]
                            )
                        else:
                            unrealized += (
                                p["direction"]
                                * (float(mark.open) - p["entry_price"])
                                * p["remaining_quantity"]
                            )
                    state = dict(
                        symbol_open=symbol in positions,
                        symbol_entered_today=(day, symbol) in entered_days,
                        open_positions=len(positions),
                        daily_entries=daily_entries[day],
                        daily_realized_pnl=daily_net[day],
                        daily_realized_loss=daily_loss[day],
                        unrealized_pnl=unrealized,
                        equity=policy["capital"] + realized + unrealized,
                        realized_pnl=realized,
                        committed=committed,
                        open_entry_fees=open_fees,
                    )
                    gate = admit(
                        policy,
                        plan=plan,
                        score=100.0,
                        confidence=event["consensus_score"],
                        now=stamp.to_pydatetime(),
                        state=state,
                    )
                    if not gate["approved"]:
                        rejects.update(gate["reasons"])
                        continue
                    qty = gate["quantity"]
                    spent = qty * price + execution_costs.fee(price, qty, costs)
                    if spent > cash + 1e-6:
                        raise RuntimeError("Shared paper cash invariant failed")
                    cash -= spent
                    committed += qty * price
                    positions[symbol] = {
                        **plan,
                        "symbol": symbol,
                        "entry_at": stamp.isoformat(),
                        "entry_signal_at": event["stamp"].isoformat(),
                        "entry_price": price,
                        "entry_raw_price": float(bar.open),
                        "quantity": qty,
                        "remaining_quantity": qty,
                        "exit_legs": [],
                    }
                    processed_native.pop(symbol, None)
                    active_daily.pop(symbol, None)
                    entered_days.add((day, symbol))
                    daily_entries[day] += 1
                    opened_scan += 1
                    max_positions = max(max_positions, len(positions))
        for symbol in list(positions):
            bar = quote(symbol, stamp)
            if bar is None:
                continue
            p = positions[symbol]
            sign = p["direction"]
            if (
                p.get("stop_is_resting_order")
                and sign * (float(bar.low if sign > 0 else bar.high) - p["stoploss"])
                <= 0
            ):
                close(
                    symbol,
                    min(float(bar.open), p["stoploss"])
                    if sign > 0
                    else max(float(bar.open), p["stoploss"]),
                    stamp,
                    "STOPLOSS",
                )
                continue
            if (
                p.get("annual")
                and not p["partial_taken"]
                and bar.high >= p["partial_target"]
            ):
                close(
                    symbol,
                    max(float(bar.open), p["partial_target"]),
                    stamp,
                    "R1_PARTIAL_PROFIT",
                    p["quantity"] // 2,
                    p["partial_target"],
                )
                p["partial_taken"] = True
            target = p.get("target2")
            if (
                target is not None
                and sign * (float(bar.high if sign > 0 else bar.low) - target) >= 0
            ):
                close(
                    symbol,
                    max(float(bar.open), target)
                    if sign > 0
                    else min(float(bar.open), target),
                    stamp,
                    "R3_FINAL_TARGET" if p.get("annual") else "STRATEGY_TARGET",
                    limit=target,
                )
                continue
            previous_marks[symbol] = float(bar.close)
        if offset == len(timeline) - 1:
            for symbol in list(positions):
                bar = quote(symbol, stamp)
                if bar is None:
                    raise ValueError(
                        "Final observed mark missing; cannot invent liquidation"
                    )
                close(
                    symbol,
                    float(bar.close),
                    stamp + pd.Timedelta(minutes=15),
                    "END_OF_TEST",
                )
        market = sum(
            p["remaining_quantity"]
            * (
                p["entry_price"]
                + p["direction"]
                * (previous_marks.get(s, p["entry_price"]) - p["entry_price"])
            )
            for s, p in positions.items()
        )
        curve.append(
            dict(
                date=(stamp + pd.Timedelta(minutes=15)).isoformat(),
                equity=cash + market,
                cash=cash,
                open_positions=len(positions),
                capital_committed=committed,
            )
        )
        minimum_cash = min(minimum_cash, cash)
        if (
            cash < -1e-6
            or committed > policy["max_deployed_capital"] + 1e-6
            or len(positions) > min(3, policy["max_open_positions"])
        ):
            raise RuntimeError("Shared paper account invariant failed")
    net = cash - policy["capital"]
    if abs(net - sum(t["net_pnl"] for t in trades)) > 0.01:
        raise RuntimeError("Shared paper trade ledger does not reconcile")
    wins = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    losses = -sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
    peak, drawdown = policy["capital"], 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        drawdown = max(drawdown, 100 * (peak - point["equity"]) / peak)
    return dict(
        basis="one_shared_account_all_approved_pairs",
        status="blocked_by_scan_coverage"
        if not trades and rejects["scan_not_fully_completed"]
        else "completed_research",
        requested_symbols=len(symbols),
        complete_quote_bars=complete_quote_bars,
        total_quote_bars=len(timeline),
        complete_daily_inputs=complete_daily_inputs,
        initial_capital=policy["capital"],
        final_capital=cash,
        net_pnl=net,
        gross_pnl_before_transaction_costs=sum(f["gross_pnl"] for f in fills),
        transaction_costs=sum(f["transaction_costs"] for f in fills),
        profit_factor=wins / losses if losses else None,
        max_drawdown_pct=drawdown,
        total_trades=len(trades),
        max_observed_positions=max_positions,
        minimum_cash=minimum_cash,
        rejection_counts=dict(rejects),
        admission_policy_hash=fingerprint(policy),
        observation_grid="15-minute observed opens and conservative OHLC exits",
        selection_basis=(
            "all approved pairs fixed in advance; "
            "no retrospective performance-gate filtering"
        ),
        lookback="60 calendar days common to all horizons",
        start_date=timeline[0].isoformat(),
        end_date=(timeline[-1] + pd.Timedelta(minutes=15)).isoformat(),
        current_constituents_not_point_in_time=True,
        out_of_sample=False,
        research_only=True,
        paper_entries_changed=False,
        trades=trades,
        equity_curve=curve,
    )
