"""Validate the durable execution state of the eight EMA/pivot paper setups."""

import math
from datetime import datetime

from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS


def positive(value):
    if isinstance(value, bool):
        raise ValueError("Invalid staged paper price")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Invalid staged paper price")
    return value


def validate_plan(key, plan, *, entry, stop, target, mode, restoring=False):
    setup = EMA_PIVOT_SETUPS.get(key)
    if setup is None:
        if plan:
            raise ValueError("Staged plan requires an EMA/pivot strategy")
        return None
    if not isinstance(plan, dict) or plan.get("strategy_id") != key:
        raise ValueError("A staged paper execution plan is required")
    if mode not in {"intraday", "swing", "positional"} or (
        mode == "positional" and setup.slow != 200
    ):
        raise ValueError("Invalid staged paper timeframe")
    if setup.direction == -1 and plan.get("short_borrow_assumed") is not True:
        raise ValueError("Paper short availability must be explicitly assumed")
    atr = positive(plan.get("signal_atr"))
    initial = entry - setup.direction * setup.stop_atr * atr
    partial = entry + setup.direction * setup.partial_r * setup.stop_atr * atr
    expected_target = (
        entry + setup.direction * setup.final_r * setup.stop_atr * atr
        if setup.final_r
        else 0.0
    )
    if initial <= 0 or partial <= 0 or expected_target < 0:
        raise ValueError("Invalid staged protective levels")
    if not math.isclose(
        float(plan.get("initial_stop", 0)), initial, abs_tol=1e-6
    ) or not math.isclose(float(plan.get("partial_target", 0)), partial, abs_tol=1e-6):
        raise ValueError("Staged paper levels do not match signal ATR")
    if not math.isclose(target, expected_target, abs_tol=1e-6):
        raise ValueError("Staged final target mismatch")
    if setup.direction * (stop - initial) < -1e-6 or (
        not restoring and not math.isclose(stop, initial, abs_tol=1e-6)
    ):
        raise ValueError("Staged stop must never widen")
    if type(plan.get("partial_taken")) is not bool:
        raise ValueError("Invalid staged partial state")
    if type(plan.get("trailing")) is not bool or plan["trailing"] != setup.trailing:
        raise ValueError("Invalid staged trailing state")
    if plan.get("best_close") is not None:
        positive(plan["best_close"])
    if plan.get("last_candle_at") is not None:
        datetime.fromisoformat(plan["last_candle_at"])
    return dict(plan)


def new_plan(key, risk, *, short_borrow_assumed=False):
    setup = EMA_PIVOT_SETUPS[key]
    return {
        "strategy_id": key,
        "signal_atr": risk["signal_atr"],
        "initial_stop": risk["stoploss"],
        "partial_target": risk["partial_target"],
        "partial_taken": False,
        "best_close": None,
        "last_candle_at": None,
        "trailing": setup.trailing,
        "short_borrow_assumed": short_borrow_assumed,
    }
