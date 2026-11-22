"""Owner-approved table rules, horizon roles and shared causal exit decisions.

This module has no order-submission capability. Both historical execution and
paper monitors consume the same plans and completed-candle exit transitions.
"""

import math
from types import SimpleNamespace

import pandas as pd

from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from scanner.portfolio_policy import number
from scanner.vwma_yearly import entry_plan as annual_plan
from scanner.vwma_yearly import opening_gap_exit, stop_conditions

LEGACY_VERSION = "approved-horizon-strategies-v1"
VERSION = "approved-horizon-strategies-v2-ema-periods"
SUPPORTED_VERSIONS = frozenset({LEGACY_VERSION, VERSION})
STATUS = "approved_horizon_execution"
IDS = (
    "tf_intraday_ema9_20_momentum",
    "tf_intraday_vwma9_26_rsi_volume",
    "tf_swing_ema20_50_rsi_volume",
    "tf_swing_vwma9_26_rsi_volume",
    "tf_medium_ema50_100",
    "tf_long_ema100_200",
    "tf_intraday_ema9_20_short",
    "tf_intraday_vwma9_26_short",
    "tf_intraday_vwap_breakdown_short",
    "tf_intraday_low20_breakdown_short",
    "tf_intraday_ema_adx_continuation_short",
    *EMA_PIVOT_SETUPS,
)
NUMBERS = {key: offset for offset, key in enumerate(IDS, 1)}
APPROVED_IDS = frozenset(IDS)
BEARISH = frozenset(IDS[i - 1] for i in (7, 8, 9, 10, 11, 13, 15, 17, 19))
VWMA = frozenset(IDS[i - 1] for i in (2, 4, 8))
LEVELS = ("P", "S1", "S2", "R1", "R2")
KEYS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "EMA_9",
    "EMA_20",
    "EMA_26",
    "EMA_50",
    "EMA_100",
    "EMA_200",
    "VWMA_9",
    "VWMA_26",
    "RSI_WILDER_14",
    "VOL_SMA_20",
    "VOL_SMA_20_PREV",
    "ADX",
    "+DI",
    "-DI",
    "VWAP_SESSION",
    "LOW_20_PREV",
    "EMA_HIGH_9",
    "SWING_HIGHS_20",
    "SWING_LOWS_20",
    *(
        f"FIB_{period}_{level}"
        for period in ("DAY", "WEEK", "MONTH", "YEAR")
        for level in (*LEVELS, "R3", "S3")
    ),
    "FIB_MONTH_LOW",
    "EMA_RESEARCH_BARS",
)


def active(key):
    if key not in APPROVED_IDS:
        return False
    from scanner.strategy_registry import get_strategy

    return get_strategy(key).get("implementation_status") == STATUS


def horizons(key, *, policy_version=VERSION):
    n = NUMBERS[key]
    if policy_version == VERSION:
        if n in (5, 6, 16, 17, 18, 19):
            return ("long_term",)
        if n in (12, 13):
            return ("intraday",)
        if n in (14, 15):
            return ("short_swing", "short_term")
    if n in (1, 2, 7, 8, 9, 10, 11):
        return ("intraday",)
    if n in (3, 4):
        return ("short_swing", "short_term")
    if n == 5:
        return ("medium_term",)
    if n == 6:
        return ("long_term",)
    return (
        "intraday",
        "short_swing"
        if n <= 13
        else "short_term"
        if n <= 15
        else "medium_term"
        if n <= 17
        else "long_term",
    )


def context_for(
    key,
    mode,
    interval=None,
    *,
    horizon=None,
    tick_size=0.05,
    liquidity_confirmation=False,
    policy_version=VERSION,
):
    if policy_version not in SUPPORTED_VERSIONS:
        raise ValueError("Unsupported approved policy version")
    allowed = horizons(key, policy_version=policy_version)
    if horizon is None and policy_version == VERSION and "short_term" in allowed:
        horizon = "short_term"
    if horizon is None:
        horizon = (
            "intraday"
            if mode == "intraday"
            else next((h for h in allowed if h != "intraday"), None)
        )
    if horizon not in allowed:
        raise ValueError("Strategy is unavailable for this trading horizon")
    expected_mode = (
        "intraday"
        if horizon == "intraday"
        else "positional"
        if horizon == "long_term"
        else "swing"
    )
    if mode != expected_mode:
        raise ValueError("Strategy mode does not match its horizon")
    expected = "15m" if horizon == "intraday" else "1d"
    if interval is not None and interval != expected:
        raise ValueError("Strategy candle interval does not match its horizon")
    return SimpleNamespace(
        mode=mode,
        interval=expected,
        horizon=horizon,
        tick_size=tick_size,
        liquidity_confirmation=liquidity_confirmation,
        policy_version=policy_version,
    )


def period_pair(key, context=None):
    """Canonical periods; persisted v1 positions retain their original exits."""
    n = NUMBERS[key]
    legacy = getattr(context, "policy_version", VERSION) == LEGACY_VERSION
    if n in (1, 7):
        return (9, 20) if legacy else (9, 26)
    if n in (2, 4, 8):
        return (9, 26)
    if n == 3:
        return (20, 50)
    if n == 5:
        return (50, 100)
    if n == 6:
        return (100, 200)
    setup = EMA_PIVOT_SETUPS.get(key)
    return (setup.fast, setup.slow) if setup else None


def continuation_ema(context):
    return "EMA_20" if context.policy_version == LEGACY_VERSION else "EMA_26"


def annual(key, context):
    return context.horizon in {"medium_term", "long_term"}


def exit_only(key, mode):
    return key in BEARISH and mode != "intraday"


def direction(key, mode):
    return -1 if key in BEARISH and mode == "intraday" else 1


def tick_price(value, tick, up):
    value, tick = number(value), number(tick)
    if value is None or tick is None or not 0 < tick <= 100:
        return None
    units = math.ceil(value / tick - 1e-9) if up else math.floor(value / tick + 1e-9)
    return units * tick


def cross(previous, current, fast, slow, sign=1):
    a, b, c, d = (number(r.get(k)) for r in (previous, current) for k in (fast, slow))
    return None not in (a, b, c, d) and sign * (a - b) <= 0 < sign * (c - d)


def above_volume(row, multiple=1.0):
    volume, average = number(row.get("volume")), number(row.get("VOL_SMA_20"))
    return None not in (volume, average) and average > 0 and volume > multiple * average


def momentum(row, sign, threshold=50):
    rsi = number(row.get("RSI_WILDER_14"))
    return rsi is not None and sign * (rsi - threshold) > 0 and above_volume(row)


def entry_period(key, context):
    n = NUMBERS[key]
    return (
        "MONTH"
        if n >= 18
        else "WEEK"
        if n >= 16 or context.mode != "intraday"
        else "DAY"
    )


def pivot_values(key, row, context):
    prefix = "FIB_" + entry_period(key, context) + "_"
    return {name: number(row.get(prefix + name)) for name in LEVELS}


def anchor(key, row, context):
    close, low, high, opening = (
        number(row.get(k)) for k in ("close", "low", "high", "open")
    )
    if None in (close, low, high, opening):
        return None
    short = key in BEARISH
    levels = pivot_values(key, row, context)
    eligible = [
        (name, value)
        for name, value in levels.items()
        if value is not None
        and value > 0
        and name in (("P", "R1", "R2") if short else ("P", "S1", "S2"))
        and (
            (high >= value > close and close < opening)
            if short
            else (low <= value < close and close > opening)
        )
    ]
    return min(eligible, key=lambda item: abs(item[1] - close)) if eligible else None


def native_entry_checks(key, previous, row, context):
    n = NUMBERS[key]
    close, average, volume = (
        number(row.get(k)) for k in ("close", "VOL_SMA_20", "volume")
    )
    checks = {"valid_completed_price": close is not None and close > 0}
    if n in (1, 2, 3, 4, 5, 6, 7, 8):
        fast, slow = period_pair(key, context)
        prefix = "VWMA" if key in VWMA else "EMA"
        sign = -1 if key in BEARISH else 1
        checks["fresh_directional_cross"] = cross(
            previous, row, f"{prefix}_{fast}", f"{prefix}_{slow}", sign
        )
        if n in (1, 5, 6):
            ema = number(row.get(f"EMA_{fast}"))
            checks["close_above_fast_ema"] = None not in (close, ema) and close > ema
        else:
            rsi = number(row.get("RSI_WILDER_14"))
            checks["directional_rsi14_50"] = rsi is not None and sign * (rsi - 50) > 0
            checks["volume_above_sma20"] = above_volume(row)
    elif n == 9:
        checks["fresh_session_vwap_breakdown"] = cross(
            previous, row, "close", "VWAP_SESSION", -1
        )
        p, c = pd.Timestamp(previous.name), pd.Timestamp(row.name)
        p, c = (
            x.tz_localize("Asia/Kolkata")
            if x.tzinfo is None
            else x.tz_convert("Asia/Kolkata")
            for x in (p, c)
        )
        checks["same_completed_intraday_pair"] = (
            p.date() == c.date() and (c - p).total_seconds() == 900
        )
        checks["volume_above_sma20"] = above_volume(row)
    elif n == 10:
        prior_low = number(row.get("LOW_20_PREV"))
        checks["close_below_prior20_low"] = (
            None not in (close, prior_low) and close < prior_low
        )
        checks["volume_above_1_5_sma20"] = above_volume(row, 1.5)
    elif n == 11:
        ema, adx, plus, minus = (
            number(row.get(k)) for k in (continuation_ema(context), "ADX", "+DI", "-DI")
        )
        checks.update(
            adx14_above25=adx is not None and adx > 25,
            negative_direction_confirms=None not in (plus, minus) and 0 <= plus < minus,
        )
        checks["close_below_" + continuation_ema(context).lower()] = (
            None not in (close, ema) and close < ema
        )
    else:
        setup = EMA_PIVOT_SETUPS[key]
        fast, slow = (
            number(row.get(f"EMA_{length}")) for length in (setup.fast, setup.slow)
        )
        checks["ema_trend"] = (
            None not in (fast, slow) and setup.direction * (fast - slow) > 0
        )
        checks["pivot_bounce_or_rejection"] = anchor(key, row, context) is not None
        if context.liquidity_confirmation:
            prior_average = number(row.get("VOL_SMA_20_PREV"))
            checks["optional_liquidity_confirmation"] = (
                None not in (volume, prior_average)
                and prior_average > 0
                and volume > 1.5 * prior_average
            )
    bars = number(row.get("EMA_RESEARCH_BARS"))
    periods = period_pair(key, context)
    required = periods[1] if periods else (26 if n == 11 else 20)
    checks["native_indicator_warmup"] = bars is not None and bars > required
    return checks


def evidence(row):
    out = {}
    for name in KEYS:
        value = row.get(name)
        if isinstance(value, (tuple, list)):
            out[name] = [float(x) for x in value if number(x) is not None]
        else:
            out[name] = number(value)
    out["signal_at"] = pd.Timestamp(row.name).isoformat()
    return out


def plan_for(key, row, context, *, entry=None):
    if exit_only(key, context.mode):
        return {}
    n, sign, tick = (
        NUMBERS[key],
        direction(key, context.mode),
        number(context.tick_size),
    )
    price = number(row.get("close") if entry is None else entry)
    if tick is None or not 0 < tick <= 100 or price is None or price <= 0:
        return {}
    plan = annual_plan(row, tick_size=tick, entry=price) if annual(key, context) else {}
    if annual(key, context) and not plan:
        return {}
    selected = anchor(key, row, context) if n >= 12 else None
    levels = pivot_values(key, row, context) if n >= 12 else {}
    target, reference = None, None
    if not annual(key, context):
        if n == 1:
            reference = number(row.get("low"))
        elif n in (2, 4, 8):
            reference = number(row.get("VWMA_26"))
        elif n == 3:
            reference = number(row.get("EMA_50"))
        elif n == 7:
            reference = next(
                (
                    number(x)
                    for x in row.get("SWING_HIGHS_20", ())
                    if number(x) is not None and x > price
                ),
                None,
            )
        elif n == 9:
            reference = number(row.get("VWAP_SESSION"))
        elif n == 10:
            reference = number(row.get("high"))
        elif n == 11:
            reference = number(row.get(continuation_ema(context)))
        elif n >= 12:
            if selected is None:
                return {}
            level = selected[1]
            if sign * (price - level) <= 0:
                return {}
            reference = level
            if n in (14, 15):
                ema = number(row.get("EMA_50"))
                if ema is None:
                    return {}
                reference = max(level, ema) if sign == 1 else min(level, ema)
            if n in (16, 17):
                reference = number(row.get("EMA_100"))
            if n in (18, 19):
                reference = number(row.get("EMA_200"))
            ahead = [
                v
                for v in levels.values()
                if v is not None and v > 0 and sign * (v - price) > 0
            ]
            target = min(ahead, key=lambda v: abs(v - price)) if ahead else None
            if n in (14, 15):
                swings = row.get("SWING_HIGHS_20" if sign == 1 else "SWING_LOWS_20", ())
                swing = next(
                    (
                        number(v)
                        for v in swings
                        if number(v) is not None and sign * (v - price) > 0
                    ),
                    None,
                )
                target = min(
                    [v for v in (target, swing) if v is not None],
                    key=lambda v: abs(v - price),
                    default=None,
                )
            if n == 18:
                target = None
            if n == 19:
                target = number(row.get("FIB_MONTH_LOW"))
            if n != 18 and (target is None or sign * (target - price) <= 0):
                return {}
        if reference is None:
            return {}
        reference = tick_price(reference - sign * tick, tick, sign < 0)
        if reference is None or reference <= 0 or sign * (price - reference) <= 0:
            return {}
        if n == 9:
            target = price - 2 * (reference - price)
        if target is not None:
            target = tick_price(target, tick, sign > 0)
            if target is None or target <= 0 or sign * (target - price) <= 0:
                return {}
        risk = sign * (price - reference)
        plan = dict(
            entry=price,
            stoploss=reference,
            target2=target,
            partial_target=None,
            risk_per_share=risk,
            reward_risk=sign * (target - price) / risk if target is not None else None,
            risk_reward="Indicator exit"
            if target is None
            else f"1:{abs(target - price) / risk:.2f}",
            stop_is_resting_order=n in (1, 7, 10),
        )
    plan.update(
        policy_version=context.policy_version,
        strategy_id=key,
        horizon=context.horizon,
        mode=context.mode,
        side="LONG" if sign == 1 else "SHORT",
        direction=sign,
        annual=annual(key, context),
        entry_order_type="NEXT_CANDLE_OPEN",
        entry_trigger=price,
        initial_stop=plan["stoploss"],
        initial_stoploss=plan["stoploss"],
        reference=plan["stoploss"],
        partial_taken=False,
        anchor_level=selected[1] if selected else None,
        anchor_name=selected[0] if selected else None,
        entry_pivots=levels,
        tick_size_assumption=tick,
        signal_evidence=evidence(row),
        trailing=plan.get("target2") is None,
        trail_ema=number(row.get("EMA_20" if n == 3 else "EMA_50"))
        if n in (3, 18)
        else None,
        last_candle_at=None,
    )
    return plan


def bearish_setup(key, previous, row, context):
    n = NUMBERS[key]
    if n in (5, 6):
        fast, slow = (50, 100) if n == 5 else (100, 200)
        return (
            cross(previous, row, f"EMA_{fast}", f"EMA_{slow}", -1)
            and number(row.get("close")) is not None
            and number(row.get(f"EMA_{fast}")) is not None
            and row["close"] < row[f"EMA_{fast}"]
        )
    if n >= 12 and key not in BEARISH:
        opposite = key.replace("_bullish_", "_bearish_")
        return all(native_entry_checks(opposite, previous, row, context).values())
    if n in (1, 7):
        fast, slow = period_pair(key, context)
        return cross(previous, row, f"EMA_{fast}", f"EMA_{slow}", 1 if n == 7 else -1)
    if n in (2, 4, 8):
        sign = 1 if n == 8 else -1
        return momentum(row, sign) and (
            cross(previous, row, "VWMA_9", "VWMA_26", sign)
            or (
                n == 4
                and number(row.get("VWMA_9")) is not None
                and row["close"] < row["VWMA_9"]
            )
        )
    if n == 3:
        ema = number(row.get("EMA_20"))
        return (
            ema is not None
            and number(row.get("close")) is not None
            and row["close"] < ema
        )
    if n == 9:
        vwap = number(row.get("VWAP_SESSION"))
        return (
            vwap is not None
            and number(row.get("close")) is not None
            and row["close"] > vwap
        )
    if n == 11:
        ema, adx, close = (
            number(row.get(k)) for k in (continuation_ema(context), "ADX", "close")
        )
        return None not in (ema, close) and close > ema or adx is not None and adx < 20
    return False


def closed_exit(previous, row, position, context):
    """Mutate only completed-bar reference state; return a next-price exit reason."""
    key = position["strategy_id"]
    n, sign = NUMBERS[key], position["direction"]
    close = number(row.get("close"))
    if close is None:
        return None
    reason = None
    if position.get("annual"):
        checks = stop_conditions(previous, row, position["stoploss"])
        gate = above_volume(row) if key in VWMA else True
        if checks["rsi_below_30_and_gap_down"] and gate:
            reason = "RSI_GAP_CLOSE_CONFIRMED_EXIT"
        elif checks["selling_volume_and_close_below_support"] and (
            key not in VWMA or momentum(row, -1)
        ):
            reason = "SELLING_VOLUME_SUPPORT_EXIT"
        elif bearish_setup(key, previous, row, context):
            reason = "BEARISH_SETUP_EXIT"
        elif position.get("partial_taken"):
            confirmed = above_volume(row)
            if row["high"] >= position["second_target"] and not (
                close > position["second_target"] and confirmed
            ):
                reason = "R2_CLOSE_CONFIRMED_PROFIT"
            if confirmed:
                cleared = [
                    position["pivot_levels"][name]
                    for name in ("R1", "R2")
                    if close > position["pivot_levels"][name]
                ]
                position["stoploss"] = max([position["stoploss"], *cleared])
        return reason
    if n in (1, 7):
        fast, slow = period_pair(key, context)
        if cross(previous, row, f"EMA_{fast}", f"EMA_{slow}", -sign):
            reason = f"EMA{fast}_{slow}_REVERSAL_EXIT"
    elif n in (2, 8):
        if momentum(row, -sign):
            if sign * (close - position["stoploss"]) < 0:
                reason = "VWMA26_CONFIRMED_STOP"
            elif cross(previous, row, "VWMA_9", "VWMA_26", -sign):
                reason = "VWMA9_26_CONFIRMED_EXIT"
    elif n == 3:
        ema, prior_ema = number(row.get("EMA_50")), number(previous.get("EMA_50"))
        entry_at = pd.Timestamp(position.get("entry_at", row.name))
        if (
            None not in (ema, prior_ema)
            and (
                pd.Timestamp(previous.name).normalize() >= entry_at.normalize()
                if context.interval == "1d"
                else pd.Timestamp(previous.name) >= entry_at
            )
            and previous["close"] < prior_ema
            and close < ema
        ):
            reason = "EMA50_TWO_DAILY_CLOSES_STOP"
    elif n == 4 and momentum(row, -1):
        slow, fast = number(row.get("VWMA_26")), number(row.get("VWMA_9"))
        if slow is not None and close < slow:
            reason = "VWMA26_CONFIRMED_STOP"
        elif fast is not None and close < fast:
            reason = "VWMA9_CONFIRMED_EXIT"
    elif n == 9:
        vwap = number(row.get("VWAP_SESSION"))
        if vwap is not None and close > vwap:
            reason = "VWAP_RECLAIM_EXIT"
    elif n == 11:
        ema, adx = number(row.get(continuation_ema(context))), number(row.get("ADX"))
        if ema is not None and close > ema:
            reason = continuation_ema(context).replace("_", "") + "_CONFIRMED_STOP"
        elif adx is not None and adx < 20:
            reason = "ADX_BELOW20_EXIT"
    elif n in (12, 13, 14, 15):
        bad = sign * (close - position["anchor_level"]) < 0
        ema = number(row.get("EMA_50"))
        if bad or (n in (14, 15) and ema is not None and sign * (close - ema) < 0):
            reason = (
                "PIVOT_OR_EMA50_CONFIRMED_STOP"
                if n in (14, 15)
                else "PIVOT_CONFIRMED_STOP"
            )
        elif bearish_setup(key, previous, row, context):
            reason = "BEARISH_SETUP_EXIT"
    elif n in (16, 17, 18, 19):
        ema = number(row.get("EMA_100" if n in (16, 17) else "EMA_200"))
        if ema is not None and sign * (close - ema) < 0:
            reason = (
                "EMA100_CONFIRMED_STOP" if n in (16, 17) else "EMA200_CONFIRMED_STOP"
            )
    if n in (3, 18):
        ema = number(row.get("EMA_20" if n == 3 else "EMA_50"))
        if ema is not None:
            position["trail_ema"] = max(position.get("trail_ema") or ema, ema)
            if reason is None and close < position["trail_ema"]:
                reason = "EMA20_TRAILING_EXIT" if n == 3 else "EMA50_TRAILING_EXIT"
    if n in (2, 8, 10):
        value = number(row.get("EMA_HIGH_9" if n == 10 else "VWMA_26"))
        if value is not None:
            next_ref = tick_price(
                value - sign * position["tick_size_assumption"],
                position["tick_size_assumption"],
                sign < 0,
            )
            position["stoploss"] = (max if sign == 1 else min)(
                position["stoploss"], next_ref
            )
    return reason


def opening_exit(previous, row, position):
    return bool(
        position.get("annual")
        and opening_gap_exit(previous, row)
        and (position["strategy_id"] not in VWMA or above_volume(previous))
    )


def evaluate(previous, row, context, key):
    context = context_for(
        key,
        context.mode,
        context.interval,
        horizon=getattr(context, "horizon", None),
        tick_size=context.tick_size,
        liquidity_confirmation=context.liquidity_confirmation,
    )
    checks = native_entry_checks(key, previous, row, context)
    raw_pass = all(checks.values())
    only_exit = exit_only(key, context.mode)
    plan = {} if only_exit else plan_for(key, row, context)
    if not only_exit:
        checks["valid_risk_and_exit_plan"] = bool(plan)
    if context.mode == "intraday" and not only_exit:
        stamp = pd.Timestamp(row.name)
        stamp = (
            stamp.tz_localize("Asia/Kolkata")
            if stamp.tzinfo is None
            else stamp.tz_convert("Asia/Kolkata")
        )
        checks["next_entry_before_cutoff"] = stamp.weekday() < 5 and (9, 15) <= (
            stamp.hour,
            stamp.minute,
        ) < (14, 30)
    entered = all(checks.values()) and not only_exit
    exit_now = raw_pass if only_exit else bearish_setup(key, previous, row, context)
    return dict(
        strategy_id=key,
        status="evaluated",
        signal="EXIT"
        if only_exit and exit_now
        else "SELL"
        if entered and key in BEARISH
        else "BUY"
        if entered
        else "EXIT"
        if exit_now
        else "WAIT",
        direction="SHORT" if key in BEARISH and not only_exit else "LONG",
        score=round(sum(checks.values()) / len(checks) * 100, 2),
        checks=checks,
        passed_checks=[k for k, v in checks.items() if v],
        failed_checks=[k for k, v in checks.items() if not v],
        risk=plan,
        entry_plan=plan,
        entry_state="EXIT_ONLY" if only_exit else "ARMED" if entered else "WAIT",
        exit_triggered=exit_now,
        exit_only=only_exit,
        paper_eligible=True,
        policy_version=VERSION,
        horizon=context.horizon,
        limitations=[
            "Paper only; planned conditional reference risk does not guarantee "
            "maximum loss."
        ],
    )


NAMES = (
    "Intraday EMA 9/26 Momentum",
    "Intraday VWMA 9/26 + RSI + Volume",
    "Swing EMA 20/50 + RSI + Volume",
    "Swing VWMA 9/26 + RSI + Volume",
    "Long-Term EMA 50/100",
    "Long-Term EMA 100/200",
    "Intraday Short EMA 9/26 + RSI + Volume",
    "Intraday Short VWMA 9/26 + RSI + Volume",
    "Intraday Short Session VWAP Breakdown",
    "Intraday Short 20-Candle Low Breakdown",
    "Intraday Short EMA/ADX Bearish Continuation",
    "EMA 9/26 Bullish Pivot",
    "EMA 9/26 Bearish Pivot",
    "EMA 20/50 Bullish Pivot",
    "EMA 20/50 Bearish Pivot",
    "EMA 50/100 Bullish Pivot",
    "EMA 50/100 Bearish Pivot",
    "EMA 100/200 Bullish Pivot",
    "EMA 100/200 Bearish Pivot",
)
ENTRY_TEXT = (
    "EMA9 crosses above EMA26; close above EMA9.",
    "VWMA9 crosses above VWMA26; Wilder RSI14 >50; volume >current Volume SMA20.",
    "Daily EMA20 crosses above EMA50; Wilder RSI14 >50; volume >current Volume SMA20.",
    "Daily VWMA9 crosses above VWMA26; Wilder RSI14 >50; volume >current Volume SMA20.",
    "Daily EMA50 crosses above EMA100; close above EMA50.",
    "Daily EMA100 crosses above EMA200; close above EMA100.",
    "EMA9 crosses below EMA26; Wilder RSI14 <50; volume >current Volume SMA20.",
    "VWMA9 crosses below VWMA26; Wilder RSI14 <50; volume >current Volume SMA20.",
    "Fresh same-session close crossing below session VWAP; volume "
    ">current Volume SMA20.",
    "Close below the preceding 20 candles' lowest low; volume >1.5 times "
    "current Volume SMA20.",
    "Close below EMA26; ADX14 >25; -DI >+DI.",
)


def definition(item):
    from dataclasses import replace

    if item.strategy_id not in APPROVED_IDS:
        return item
    key, n = item.strategy_id, NUMBERS[item.strategy_id]
    allowed = horizons(key)
    modes = tuple(
        dict.fromkeys(
            "intraday"
            if h == "intraday"
            else "positional"
            if h == "long_term"
            else "swing"
            for h in allowed
        )
    )
    indicators = []
    if n <= 8:
        pair = period_pair(key)
        prefix = "VWMA" if key in VWMA else "EMA"
        indicators = [f"{prefix}_{length}" for length in pair]
    elif n == 9:
        indicators = ["VWAP_SESSION"]
    elif n == 10:
        indicators = ["LOW_20_PREV", "EMA_HIGH_9"]
    elif n == 11:
        indicators = ["EMA_26", "ADX", "+DI", "-DI"]
    else:
        setup = EMA_PIVOT_SETUPS[key]
        indicators = [f"EMA_{length}" for length in (setup.fast, setup.slow)]
        if n in (18, 19):
            indicators.append("EMA_50" if n == 18 else "FIB_MONTH_LOW")
        periods = ("DAY",) if n <= 13 else ("WEEK",) if n <= 17 else ("MONTH",)
        indicators.extend(f"FIB_{p}_{level}" for p in periods for level in LEVELS)
    if n in (2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 19):
        indicators.extend(("RSI_WILDER_14", "VOL_SMA_20"))
    elif n in (9, 10):
        indicators.append("VOL_SMA_20")
    if n in (5, 6, 16, 17, 18, 19):
        indicators.extend(f"FIB_YEAR_{level}" for level in (*LEVELS, "R3", "S3"))
    entry = (
        ENTRY_TEXT[n - 1]
        if n <= 11
        else (
            "Fast EMA on the trend side of slow EMA; completed green support "
            "bounce or red resistance rejection. Use the nearest qualifying "
            "Fibonacci pivot."
        )
    )
    return replace(
        item,
        name=NAMES[n - 1],
        family="approved_horizon_rules",
        description=(
            "Approved table strategy with horizon-specific direction and exits."
        ),
        modes=modes,
        intervals=("15m", "1d")
        if len(modes) > 1
        else ("15m",)
        if modes == ("intraday",)
        else ("1d",),
        default_interval="15m" if modes == ("intraday",) else "1d",
        indicators=tuple(dict.fromkeys(indicators)),
        entry_rules=(
            entry,
            "Completed candles; fill at the next observed candle open after "
            "checking the actual fill.",
        ),
        exit_rules=(
            "Intraday shorts permitted; bearish setups in other eligible horizons "
            "exit longs or show EXIT only.",
            "Mandatory 15:00 IST intraday square-off.",
        ),
        target_rules=(
            "Shorter horizons use the approved individual indicator/pivot/2R "
            "target; Medium/Long Term use half at yearly R1 and continuation "
            "toward R2/R3.",
        ),
        stoploss_rules=(
            "Use the approved individual candle/EMA/VWMA/pivot stop for shorter "
            "horizons; Medium/Long Term retain the combined yearly-reference "
            "stops.",
            "All VWMA signal exits require RSI14 and above-average Volume SMA20 "
            "confirmation.",
        ),
        risk_rules=(
            "Shared account; no leverage or short-proceeds reuse; at most three "
            "stocks and 0.5% planned reference equity risk including fees. "
            "Conditional references do not guarantee maximum loss.",
        ),
        paper_eligible=True,
        implementation_status=STATUS,
        ambiguities=(),
        direction="SHORT" if key in BEARISH else "LONG",
        notes=(
            VERSION,
            "EMA periods: intraday 9/26; swing 20/50; long term 50/100 or "
            "100/200. Legacy strategy IDs remain stable for stored records; "
            "v1 positions retain their original exit policy.",
            "Fresh registry-matched validation, operator Start, fresh quotes and "
            "durable storage are required. Broker orders remain disabled.",
            "Reference periods are completed before the signal; no future swing "
            "confirmation. See the approved rule specification for per-strategy "
            "details.",
        ),
    )
