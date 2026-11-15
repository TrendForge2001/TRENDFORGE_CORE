"""Completed daily VWMA momentum with prior-year Fibonacci breakout levels."""

import math

import numpy as np
import pandas as pd

from indicators.ema_pivot import wilder_average
from scanner.portfolio_policy import number

STRATEGY_ID = "tf_daily_vwma20_50_rsi_fibonacci_yearly"
VERSION = "daily-vwma-yearly-fibonacci-v1"
LEVELS = ("P", "R1", "R2", "R3", "S1", "S2", "S3")
INDICATORS = (
    "VWMA_20",
    "VWMA_50",
    "RSI_WILDER_14",
    "VOL_SMA_20",
    "HIGH_20_PREV",
    "LOW_5",
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
    annual = {}
    for offset, (year, group) in enumerate(out.groupby(out.index.year)):
        # First observed year may be truncated. Allow exchange holidays at
        # calendar boundaries; coverage is not an exchange-calendar audit.
        if (
            offset == 0
            or len(group) < 200
            or group.index[0].date() > pd.Timestamp(year, 1, 10).date()
            or group.index[-1].date() < pd.Timestamp(year, 12, 20).date()
        ):
            continue
        high, low, close = group.high.max(), group.low.min(), group.close.iloc[-1]
        pivot, span = (high + low + close) / 3, high - low
        annual[int(year) + 1] = {
            "P": pivot,
            **{
                f"R{i}": pivot + ratio * span
                for i, ratio in enumerate((0.382, 0.618, 1.0), 1)
            },
            **{
                f"S{i}": pivot - ratio * span
                for i, ratio in enumerate((0.382, 0.618, 1.0), 1)
            },
        }
    for name in LEVELS:
        out["FIB_YEAR_" + name] = [
            annual.get(int(year), {}).get(name, np.nan) for year in out.index.year
        ]
    return out


def entry_plan(row, *, tick_size=0.05, entry=None):
    high, low, tick = (
        number(v) for v in (row.get("high"), row.get("LOW_5"), tick_size)
    )
    if None in (high, low, tick) or not 0 < tick <= 100 or low <= 0:
        return {}
    trigger = math.ceil(high * 1.003 / tick - 1e-9) * tick
    stop = math.floor(low * 0.997 / tick + 1e-9) * tick
    entry = trigger if entry is None else number(entry)
    if entry is None or not 0 < stop < entry:
        return {}
    risk = entry - stop
    return {
        "entry": entry,
        "entry_trigger": trigger,
        "stoploss": stop,
        "partial_target": entry + 2 * risk,
        "target2": entry + 3 * risk,
        "risk_per_share": risk,
        "reward_risk": 3.0,
        "risk_reward": "1:3.00",
        "signal_atr": None,
        "pivot_room_r": None,
        "pivot_room_sufficient": True,
        "valid_for_next_candle_only": True,
    }


def evaluate(previous, current, context=None, strategy_id=STRATEGY_ID):
    tick = context.tick_size if context is not None else 0.05
    values = {key: number(current.get(key)) for key in INDICATORS}
    ready = all(values[key] is not None for key in INDICATORS)
    c, pc = number(current.get("close")), number(previous.get("close"))
    w20, w50 = values["VWMA_20"], values["VWMA_50"]
    pw20, pw50 = (number(previous.get(key)) for key in ("VWMA_20", "VWMA_50"))
    crossed = []
    if ready and None not in (c, pc) and current.name.year == previous.name.year:
        crossed = [
            name
            for name in ("P", "R1", "R2", "R3")
            if pc <= values["FIB_YEAR_" + name] < c
        ]
    prior_high = values["HIGH_20_PREV"]
    high_break = None not in (c, pc, prior_high) and pc <= prior_high < c
    plan = entry_plan(current, tick_size=tick)
    checks = {
        "indicators_and_previous_year_ready": ready,
        "close_above_vwma20_above_vwma50": None not in (c, w20, w50) and c > w20 > w50,
        "both_vwmas_rising": None not in (w20, w50, pw20, pw50)
        and w20 > pw20
        and w50 > pw50,
        "rsi_55_to_75": values["RSI_WILDER_14"] is not None
        and 55 <= values["RSI_WILDER_14"] <= 75,
        "volume_at_least_1_5_sma20": values["VOL_SMA_20"] is not None
        and values["VOL_SMA_20"] > 0
        and (number(current.get("volume")) or 0) >= 1.5 * values["VOL_SMA_20"],
        "fresh_pivot_or_high20_breakout": bool(crossed) or high_break,
        "valid_entry_bracket": bool(plan),
    }
    armed = all(checks.values())
    return {
        "strategy_id": strategy_id,
        "signal": "BUY" if armed else "HOLD",
        "status": "evaluated",
        "score": sum(checks.values()) / len(checks) * 100,
        "entry_state": "ARMED" if armed else "WAIT",
        "checks": checks,
        "entry_plan": plan,
        "indicators": values,
        "crossed_pivots": crossed,
        "risk": plan,
        "direction": "LONG",
        "paper_eligible": False,
        "passed_checks": [key for key, value in checks.items() if value],
        "failed_checks": [key for key, value in checks.items() if not value],
        "high20_breakout": high_break,
        "exit_triggered": None not in (c, w20) and c < w20,
        "signal_semantics": (
            "Completed daily setup; next-session stop-entry trigger, not a fill"
        ),
    }
