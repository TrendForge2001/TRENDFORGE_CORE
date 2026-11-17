"""Daily VWMA crossovers at annual Fibonacci levels, with long-only exits."""

import math

import numpy as np

from indicators.ema_pivot import wilder_average
from indicators.yearly_fibonacci import annual_levels, attach_levels
from scanner.portfolio_policy import number

STRATEGY_ID = "tf_daily_vwma20_50_rsi_fibonacci_yearly"
VERSION = "daily-vwma-yearly-pivot-retest-v2"
LEVELS = ("P", "R1", "R2", "R3", "S1", "S2", "S3")
INDICATORS = (
    "VWMA_20",
    "VWMA_50",
    "RSI_WILDER_14",
    "VOL_SMA_20",
    *("FIB_YEAR_" + name for name in LEVELS),
)


def prepare_daily(frame, *, now=None):
    from scanner.weekly_floor import daily_history

    return add_indicators(daily_history(frame, now=now))


def add_indicators(daily):
    out = daily.copy()
    for length in (20, 50):
        out[f"VWMA_{length}"] = (out.close * out.volume).rolling(length).sum() / (
            out.volume.rolling(length).sum().replace(0, np.nan)
        )
    delta = out.close.diff()
    gain = wilder_average(delta.clip(lower=0))
    loss = wilder_average(-delta.clip(upper=0))
    out["RSI_WILDER_14"] = (100 - 100 / (1 + gain / loss)).where(
        (gain != 0) | (loss != 0), 50.0
    )
    out["VOL_SMA_20"] = out.volume.rolling(20).mean()
    out["HIGH_20_PREV"] = out.high.shift().rolling(20).max()
    out["LOW_5"] = out.low.rolling(5).min()
    return attach_levels(out, annual_levels(out))


def second_support(row, price):
    """Second distinct, positive annual pivot strictly below the actual fill."""
    price = number(price)
    if price is None or price <= 0:
        return None
    below = sorted(
        {
            value
            for name in LEVELS
            if (value := number(row.get("FIB_YEAR_" + name))) is not None
            and 0 < value < price
        },
        reverse=True,
    )
    return below[1] if len(below) >= 2 else None


def entry_plan(row, *, tick_size=0.05, entry=None):
    """Estimate at the signal close; recompute sizing at the next open fill."""
    tick = number(tick_size)
    price = number(row.get("close") if entry is None else entry)
    reference = second_support(row, price)
    levels = {name: number(row.get("FIB_YEAR_" + name)) for name in LEVELS}
    if (
        tick is None
        or not 0 < tick <= 100
        or price is None
        or reference is None
        or not 0 < reference < price
        or any(levels[name] is None for name in ("R1", "R2", "R3"))
        or not price < levels["R1"] < levels["R2"] < levels["R3"]
    ):
        return {}
    targets = {
        name: math.ceil(levels[name] / tick - 1e-9) * tick
        for name in ("R1", "R2", "R3")
    }
    if not targets["R1"] < targets["R2"] < targets["R3"]:
        return {}
    risk = price - reference
    reward_risk = (targets["R3"] - price) / risk
    return {
        "entry": price,
        "entry_trigger": price,
        "entry_order_type": "NEXT_SESSION_OPEN",
        "stoploss": reference,
        "conditional_stop_reference": reference,
        "stop_is_resting_order": False,
        "partial_target": targets["R1"],
        "second_target": targets["R2"],
        "target2": targets["R3"],
        "pivot_levels": levels,
        "risk_per_share": risk,
        "reward_risk": reward_risk,
        "risk_reward": f"1:{reward_risk:.2f}",
        "signal_atr": None,
        "pivot_room_r": None,
        "pivot_room_sufficient": True,
        "valid_for_next_candle_only": True,
    }


def stop_conditions(previous, current, reference):
    """Close-confirmed conditional exits. No price-only protective stop."""
    rsi, opening, previous_close, close, volume, average, reference = (
        number(value)
        for value in (
            current.get("RSI_WILDER_14"),
            current.get("open"),
            previous.get("close"),
            current.get("close"),
            current.get("volume"),
            current.get("VOL_SMA_20"),
            reference,
        )
    )
    return {
        "rsi_below_30_and_gap_down": None not in (rsi, opening, previous_close)
        and rsi < 30
        and opening < previous_close,
        "selling_volume_and_close_below_support": None
        not in (close, opening, volume, average, reference)
        and average > 0
        and reference > 0
        and close < opening
        and volume > average
        and close < reference,
    }


def opening_gap_exit(previous, current):
    """Only the previous completed RSI is knowable at today's opening fill."""
    rsi, close, opening = (
        number(value)
        for value in (
            previous.get("RSI_WILDER_14"),
            previous.get("close"),
            current.get("open"),
        )
    )
    return None not in (rsi, close, opening) and rsi < 30 and opening < close


def evaluate(previous, current, context=None, strategy_id=STRATEGY_ID):
    tick = context.tick_size if context is not None else 0.05
    values = {key: number(current.get(key)) for key in INDICATORS}
    ready = all(value is not None for value in values.values())
    close, low, high, volume = (
        number(current.get(key)) for key in ("close", "low", "high", "volume")
    )
    fast, slow = values["VWMA_20"], values["VWMA_50"]
    pfast, pslow, prsi = (
        number(previous.get(key)) for key in ("VWMA_20", "VWMA_50", "RSI_WILDER_14")
    )
    rsi, average = values["RSI_WILDER_14"], values["VOL_SMA_20"]
    up = None not in (fast, slow, pfast, pslow) and pfast <= pslow and fast > slow
    down = None not in (fast, slow, pfast, pslow) and pfast >= pslow and fast < slow
    supports = [
        name
        for name in ("P", "S1", "S2", "S3")
        if None not in (low, close, values["FIB_YEAR_" + name])
        and low <= values["FIB_YEAR_" + name] < close
    ]
    resistances = [
        name
        for name in ("P", "R1", "R2", "R3")
        if None not in (high, close, values["FIB_YEAR_" + name])
        and close < values["FIB_YEAR_" + name] <= high
    ]
    participation = None not in (volume, average) and average > 0 and volume > average
    plan = entry_plan(current, tick_size=tick)
    checks = {
        "indicators_and_previous_year_ready": ready,
        "yearly_support_test_and_close_above": bool(supports),
        "vwma20_crosses_above_vwma50": up,
        "rsi_above_50_through_70": rsi is not None and 50 < rsi <= 70,
        "volume_above_sma20": participation,
        "valid_actual_entry_and_pivot_references": bool(plan),
    }
    bearish_checks = {
        "indicators_and_previous_year_ready": ready,
        "yearly_resistance_rejection": bool(resistances),
        "vwma20_crosses_below_vwma50": down,
        "rsi_crosses_below_50": None not in (rsi, prsi) and prsi >= 50 and rsi < 50,
        "volume_above_sma20": participation,
    }
    armed = all(checks.values())
    gap_exit = stop_conditions(previous, current, None)["rsi_below_30_and_gap_down"]
    exit_long = all(bearish_checks.values()) or gap_exit
    score = (
        (100 if rsi <= 65 else 95) if armed else sum(checks.values()) / len(checks) * 90
    )
    return {
        "strategy_id": strategy_id,
        "signal": "BUY" if armed else "EXIT" if exit_long else "HOLD",
        "status": "evaluated",
        "score": score,
        "entry_state": "ARMED" if armed else "WAIT",
        "checks": checks,
        "bearish_exit_checks": bearish_checks,
        "rsi_gap_exit_confirmed": gap_exit,
        "entry_plan": plan,
        "indicators": values,
        "tested_supports": supports,
        "rejected_resistances": resistances,
        "risk": plan,
        "direction": "LONG",
        "paper_eligible": False,
        "passed_checks": [key for key, value in checks.items() if value],
        "failed_checks": [key for key, value in checks.items() if not value],
        "exit_triggered": exit_long,
        "signal_semantics": (
            "Completed daily signal; next-session open; "
            "bearish setups exit existing longs only"
        ),
    }
