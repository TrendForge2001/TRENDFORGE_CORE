"""Causal native swing references and Fibonacci entry pivots from daily HLC."""

from collections import deque

import numpy as np

from indicators.ema_pivot import wilder_average
from indicators.yearly_fibonacci import annual_levels, attach_levels

LEVELS = ("P", "S1", "S2", "R1", "R2", "S3", "R3")


def fibonacci(high, low, close):
    p, span = (high + low + close) / 3.0, high - low
    return {
        "P": p,
        "LOW": low,
        **{
            f"{side}{i}": p + sign * ratio * span
            for side, sign in (("R", 1), ("S", -1))
            for i, ratio in enumerate((0.382, 0.618, 1.0), 1)
        },
    }


def reference_maps(daily):
    """Compact immutable HLC-derived maps; never retain the daily frame in cache."""
    local = (
        daily.index.tz_convert("Asia/Kolkata")
        if daily.index.tz is not None
        else daily.index
    )
    records = {}
    for period, freq in (("DAY", "D"), ("WEEK", "W-SUN"), ("MONTH", "M")):
        keys = (
            local.tz_localize(None).to_period(freq)
            if local.tz is not None
            else local.to_period(freq)
        )
        grouped = daily.groupby(keys).agg(
            high=("high", "max"), low=("low", "min"), close=("close", "last")
        )
        values = {
            p.ordinal: fibonacci(row.high, row.low, row.close)
            for p, row in grouped.iterrows()
        }
        if period != "DAY" and len(grouped):
            values.pop(grouped.index[0].ordinal, None)
        records[period] = values
    records["YEAR"] = annual_levels(daily)
    return records


def attach_references(frame, maps):
    out = attach_levels(frame, maps.get("YEAR", {}))
    local = (
        frame.index.tz_convert("Asia/Kolkata")
        if frame.index.tz is not None
        else frame.index
    )
    naive = local.tz_localize(None) if local.tz is not None else local
    for period, freq in (("DAY", "D"), ("WEEK", "W-SUN"), ("MONTH", "M")):
        source = maps[period]
        keys = naive.to_period(freq).asi8
        if period == "DAY":
            observed = np.asarray(sorted(source), dtype=np.int64)
            offsets = np.searchsorted(observed, keys, side="left") - 1
            previous = [
                source.get(int(observed[i]), {}) if i >= 0 else {} for i in offsets
            ]
        else:
            previous = [source.get(int(key) - 1, {}) for key in keys]
        for level in (*LEVELS, "LOW"):
            out[f"FIB_{period}_{level}"] = [
                values.get(level, np.nan) for values in previous
            ]
    return out


def add_native(frame):
    out = frame.copy()
    if "RSI_WILDER_14" not in out:
        delta = out.close.diff()
        gain, loss = (
            wilder_average(delta.clip(lower=0)),
            wilder_average(-delta.clip(upper=0)),
        )
        out["RSI_WILDER_14"] = (100 - 100 / (1 + gain / loss)).where(
            (gain != 0) | (loss != 0), 50.0
        )
    if "VOL_SMA_20" not in out:
        out["VOL_SMA_20"] = out.volume.rolling(20).mean()
    out["VOL_SMA_20_PREV"] = out.volume.shift().rolling(20).mean()
    out["LOW_20_PREV"] = out.low.shift().rolling(20).min()
    out["EMA_HIGH_9"] = out.high.ewm(span=9, adjust=False).mean()
    pools = {"high": deque(), "low": deque()}
    data = {name: out[name].to_numpy(dtype=float) for name in pools}
    result = {name: [] for name in pools}
    for offset in range(len(out)):
        candidate = offset - 3  # right-side confirmation finished before trigger
        for name, pool in pools.items():
            values = data[name]
            if candidate >= 2:
                neighbors = values[
                    [candidate - 2, candidate - 1, candidate + 1, candidate + 2]
                ]
                value = values[candidate]
                if (
                    np.isfinite(value)
                    and np.isfinite(neighbors).all()
                    and (
                        (value > neighbors).all()
                        if name == "high"
                        else (value < neighbors).all()
                    )
                ):
                    pool.appendleft((candidate, float(value)))
            while pool and pool[-1][0] < offset - 20:
                pool.pop()
            result[name].append(tuple(value for _, value in pool))
    out["SWING_HIGHS_20"] = result["high"]
    out["SWING_LOWS_20"] = result["low"]
    return out
