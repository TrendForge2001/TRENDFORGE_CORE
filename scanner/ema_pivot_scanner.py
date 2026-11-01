"""Completed-candle setup detection and next-candle research entry plans."""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

import pandas as pd

from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS, EmaPivotSetup
from scanner.portfolio_policy import number


def crossed(previous, current, left: str, right: str, direction: int) -> bool:
    values = [
        number(row.get(key)) for row in (previous, current) for key in (left, right)
    ]
    if None in values:
        return False
    a, b, c, d = values
    return direction * (a - b) <= 0 < direction * (c - d)


def pivot_plan(
    setup: EmaPivotSetup, row, *, mode: str, tick_size: float = 0.05, entry=None
) -> dict:
    """Re-anchor risk to an actual fill and recheck directional pivot headroom."""
    atr = number(row.get("ATR_WILDER_14"))
    extreme = number(row.get("high" if setup.direction == 1 else "low"))
    tick = number(tick_size)
    if (
        atr is None
        or atr <= 0
        or extreme is None
        or extreme <= 0
        or tick is None
        or tick <= 0
    ):
        return {}
    unit = Decimal(str(tick))
    price = Decimal(str(extreme)) / unit
    price = price.to_integral_value(
        rounding=ROUND_FLOOR if setup.direction == 1 else ROUND_CEILING
    )
    trigger = float((price + setup.direction) * unit)
    entry = trigger if entry is None else number(entry)
    if entry is None or entry <= 0:
        return {}
    risk = setup.stop_atr * atr
    stop = entry - setup.direction * risk
    partial = entry + setup.direction * setup.partial_r * risk
    target = entry + setup.direction * setup.final_r * risk if setup.final_r else None
    if stop <= 0 or partial <= 0 or (target is not None and target <= 0):
        return {}
    prefix = f"TRAD_{setup.pivot_period(mode)}_"
    levels = {
        key: number(row.get(prefix + key)) for key in ("P", "R1", "R2", "S1", "S2")
    }
    if any(value is None or value <= 0 for value in levels.values()):
        return {}
    ahead = [
        value for value in levels.values() if setup.direction * (value - entry) > 0
    ]
    nearest = min(ahead, key=lambda value: abs(value - entry)) if ahead else None
    room = setup.direction * (nearest - entry) / risk if nearest is not None else None
    return {
        "entry": entry,
        "entry_trigger": trigger,
        "stoploss": stop,
        "target2": target,
        "partial_target": partial,
        "risk_per_share": risk,
        "signal_atr": atr,
        "reward_risk": setup.final_r,
        "risk_reward": f"1:{setup.final_r:g}"
        if setup.final_r
        else f"Half at 1:{setup.partial_r:g}; remainder trails",
        "partial_r": setup.partial_r,
        "partial_fraction": 0.5,
        "trailing_atr": 3.0 if setup.trailing else None,
        "move_stop_to_entry_after_partial": not setup.trailing,
        "pivot_period": setup.pivot_period(mode).lower(),
        "pivot_levels": levels,
        "nearest_directional_pivot": nearest,
        "pivot_room_r": room,
        "pivot_room_sufficient": room is None or room >= 1.5 - 1e-9,
        "pivot_room_note": "No further level in P/R1/R2/S1/S2"
        if nearest is None
        else "Nearest directional traditional pivot",
        "valid_for_next_candle_only": True,
        "risk_fraction": 0.005,
        "tick_size_assumption": tick,
    }


def evaluate_ema_pivot(previous, current, context, strategy_id: str) -> dict:
    setup = EMA_PIVOT_SETUPS[strategy_id]
    direction = setup.direction
    fast, slow = f"EMA_{setup.fast}", f"EMA_{setup.slow}"
    close, ema_fast, ema_slow, low, high = (
        number(current.get(k)) for k in ("close", fast, slow, "low", "high")
    )
    rsi, previous_rsi = (
        number(current.get("RSI_WILDER_14")),
        number(previous.get("RSI_WILDER_14")),
    )
    macd, signal, hist = (
        number(current.get(k)) for k in ("MACD", "MACD_SIGNAL", "MACD_HIST")
    )
    prior_hist = number(previous.get("MACD_HIST"))
    prefix = f"TRAD_{setup.pivot_period(context.mode)}_"
    pivot = number(current.get(prefix + "P"))
    plan = pivot_plan(setup, current, mode=context.mode, tick_size=context.tick_size)
    checks = {
        "ema_warmup_complete": (number(current.get("EMA_RESEARCH_BARS")) or 0)
        >= setup.slow + 1,
        "valid_signal_candle": None not in (close, high, low)
        and 0 < low <= close <= high,
        "rsi_in_range": rsi is not None and setup.rsi_min <= rsi <= setup.rsi_max,
        "macd_direction_confirms": None not in (macd, signal)
        and direction * (macd - signal) > 0,
        "close_on_pivot_side": None not in (close, pivot)
        and direction * (close - pivot) > 0,
        "positive_atr_bracket": bool(plan),
        "pivot_room_at_least_1_5r": bool(plan.get("pivot_room_sufficient")),
    }
    if setup.fast == 50:
        checks.update(
            {
                "ema_trend": None not in (ema_fast, ema_slow)
                and direction * (ema_fast - ema_slow) > 0,
                "ema50_touch_and_rejection": None not in (low, high, close, ema_fast)
                and low <= ema_fast <= high
                and direction * (close - ema_fast) > 0,
                "rsi_crosses_50": None not in (previous_rsi, rsi)
                and direction * (previous_rsi - 50) <= 0 < direction * (rsi - 50),
            }
        )
    else:
        checks.update(
            {
                "fresh_ema_cross": crossed(previous, current, fast, slow, direction),
                "close_beyond_both_emas": None not in (close, ema_fast, ema_slow)
                and direction * (close - ema_fast) > 0
                and direction * (close - ema_slow) > 0,
            }
        )
    if setup.fast in (9, 50):
        checks["histogram_improving"] = (
            None not in (hist, prior_hist) and direction * (hist - prior_hist) > 0
        )
        if setup.fast == 9:
            checks["histogram_on_correct_side"] = (
                hist is not None and direction * hist > 0
            )
    else:
        checks["macd_on_correct_side_of_zero"] = (
            macd is not None and direction * macd > 0
        )
    if context.liquidity_confirmation:
        volume, average = (
            number(current.get("volume")),
            number(current.get("VOL_SMA_20_PREV")),
        )
        checks["volume_above_1_5_previous20"] = (
            None not in (volume, average) and average > 0 and volume > 1.5 * average
        )
    if context.mode == "intraday":
        try:
            p, c = (pd.Timestamp(row.name) for row in (previous, current))
            p, c = (
                stamp.tz_localize("Asia/Kolkata")
                if stamp.tzinfo is None
                else stamp.tz_convert("Asia/Kolkata")
                for stamp in (p, c)
            )
            checks["same_session_completed_pair"] = (
                p.date() == c.date() and (c - p).total_seconds() == 900
            )
            checks["next_entry_in_session"] = c.weekday() < 5 and (9, 15) <= (
                c.hour,
                c.minute,
            ) < (14, 30)
        except (TypeError, ValueError):
            checks["same_session_completed_pair"] = checks["next_entry_in_session"] = (
                False
            )
    exit_now = None not in (close, ema_fast) and direction * (close - ema_fast) < 0
    if setup.fast == 9:
        exit_now = exit_now or crossed(
            previous, current, "MACD", "MACD_SIGNAL", -direction
        )
    if setup.fast == 20 and rsi is not None:
        exit_now = exit_now or (rsi < 45 if direction == 1 else rsi > 55)
    armed = all(checks.values())
    return {
        "strategy_id": strategy_id,
        "status": "evaluated",
        "signal": ("BUY" if direction == 1 else "SELL")
        if armed
        else "EXIT"
        if exit_now
        else "WAIT",
        "direction": "LONG" if direction == 1 else "SHORT",
        "score": round(sum(checks.values()) / len(checks) * 100, 2),
        "checks": checks,
        "passed_checks": [k for k, v in checks.items() if v],
        "failed_checks": [k for k, v in checks.items() if not v],
        "risk": plan,
        "entry_plan": plan,
        "entry_state": "ARMED" if armed else "WAIT",
        "exit_triggered": bool(exit_now),
        "paper_eligible": False,
        "limitations": [
            "Research setup, not a fill. Next-candle trigger, partial exits and "
            "trailing stops are simulated only; no automatic paper or broker orders."
        ],
    }
