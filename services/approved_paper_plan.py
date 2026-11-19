"""Validate and advance durable approved-rule paper plans without broker access."""

import math
from copy import deepcopy

import pandas as pd

from scanner import approved_strategies as rules


def is_approved(plan):
    return isinstance(plan, dict) and plan.get("policy_version") == rules.VERSION


def from_signal(key, plan, entry):
    if not is_approved(plan) or plan.get("strategy_id") != key:
        raise ValueError("Approved rule execution plan required")
    source = plan.get("signal_evidence")
    if not isinstance(source, dict) or not source.get("signal_at"):
        raise ValueError("Completed signal evidence required")
    row = pd.Series(source, name=pd.Timestamp(source["signal_at"]))
    context = rules.context_for(
        key,
        plan.get("mode"),
        horizon=plan.get("horizon"),
        tick_size=plan.get("tick_size_assumption"),
    )
    result = rules.plan_for(key, row, context, entry=entry)
    if not result:
        raise ValueError("Actual quote invalidates the approved reference or target")
    return result


def validate(key, plan, *, entry, stop, target, mode, restoring=False):
    from services.approved_admission import economics

    economics(plan, entry)
    expected = from_signal(key, plan, entry)
    if mode != expected["mode"] or rules.exit_only(key, mode):
        raise ValueError("Approved paper direction or mode mismatch")
    for field in ("side", "direction", "annual", "stop_is_resting_order", "trailing"):
        if plan.get(field) != expected.get(field):
            raise ValueError("Approved paper plan policy mismatch")
    for field in (
        "initial_stop",
        "initial_stoploss",
        "partial_target",
        "second_target",
        "anchor_level",
        "target2",
    ):
        value, reference = plan.get(field), expected.get(field)
        if (value is None) != (reference is None) or (
            reference is not None
            and not math.isclose(float(value), float(reference), abs_tol=1e-6)
        ):
            raise ValueError("Approved paper frozen levels mismatch")
    if plan.get("pivot_levels") != expected.get("pivot_levels") or plan.get(
        "entry_pivots"
    ) != expected.get("entry_pivots"):
        raise ValueError("Approved paper frozen pivots mismatch")
    if not math.isclose(target, expected.get("target2") or 0.0, abs_tol=1e-6):
        raise ValueError("Approved paper target mismatch")
    initial = expected["initial_stop"]
    if expected["direction"] * (stop - initial) < -1e-6 or (
        not restoring and not math.isclose(stop, initial, abs_tol=1e-6)
    ):
        raise ValueError("Approved paper reference must never widen")
    if not math.isclose(float(plan.get("stoploss", 0)), stop, abs_tol=1e-6):
        raise ValueError("Approved paper active reference mismatch")
    if type(plan.get("partial_taken")) is not bool or (
        not restoring and plan["partial_taken"]
    ):
        raise ValueError("Invalid approved partial state")
    if plan.get("last_candle_at"):
        pd.Timestamp(plan["last_candle_at"])
    if plan.get("trail_ema") is not None and rules.number(plan["trail_ema"]) is None:
        raise ValueError("Invalid approved EMA trail")
    return deepcopy(plan)


def advance(runtime, symbol, previous, row):
    """Persist state before a fresh-quote close; retry a pending exit after errors."""
    with runtime._state_lock:
        position = runtime.portfolio.positions.get(symbol)
        if position is None or not is_approved(position.paper_plan):
            return None
        plan = deepcopy(position.paper_plan)
        if plan.get("pending_exit_reason"):
            return plan["pending_exit_reason"]
        stamp = pd.Timestamp(row.name)
        stamp = (
            stamp.tz_localize("Asia/Kolkata")
            if stamp.tzinfo is None
            else stamp.tz_convert("Asia/Kolkata")
        )
        entered = pd.Timestamp(position.entry_at)
        entered = (
            entered.tz_localize("Asia/Kolkata")
            if entered.tzinfo is None
            else entered.tz_convert("Asia/Kolkata")
        )
        if stamp.date() < entered.date() or (
            position.trade_mode == "intraday"
            and stamp + pd.Timedelta(minutes=15) <= entered
        ):
            return None
        if plan.get("last_candle_at") and stamp <= pd.Timestamp(plan["last_candle_at"]):
            return None
        context = rules.context_for(
            position.strategy_id,
            position.trade_mode,
            horizon=plan["horizon"],
            tick_size=plan["tick_size_assumption"],
        )
        plan.update(
            entry_at=entered.normalize().isoformat()
            if context.interval == "1d"
            else entered.isoformat(),
            stoploss=position.stoploss,
        )
        reason = rules.closed_exit(previous, row, plan, context)
        plan["last_candle_at"] = stamp.isoformat()
        if reason:
            plan["pending_exit_reason"] = reason
        runtime.trades.update_paper_plan(
            runtime._trade_ids[symbol], plan, plan["stoploss"]
        )
        position.paper_plan, position.stoploss = plan, plan["stoploss"]
        return reason


def observe_opening(runtime, symbol, previous, current):
    """Opening-gap evidence needs only prior closed indicators and the new open."""
    with runtime._state_lock:
        position = runtime.portfolio.positions.get(symbol)
        if position is None or not is_approved(position.paper_plan):
            return None
        plan = deepcopy(position.paper_plan)
        if plan.get("pending_exit_reason"):
            return plan["pending_exit_reason"]
        if pd.Timestamp(current.name).date() < pd.Timestamp(position.entry_at).date():
            return None
        if rules.opening_exit(previous, current, plan):
            plan["pending_exit_reason"] = "RSI_GAP_OPEN_EXIT"
            runtime.trades.update_paper_plan(
                runtime._trade_ids[symbol], plan, position.stoploss
            )
            position.paper_plan = plan
            return plan["pending_exit_reason"]
        return None
