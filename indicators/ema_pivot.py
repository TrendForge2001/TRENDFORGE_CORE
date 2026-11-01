"""Causal research indicators; existing legacy RSI/ATR/pivots stay unchanged."""

import numpy as np
import pandas as pd


def wilder_average(values: pd.Series, length: int = 14) -> pd.Series:
    """Seed with the first full SMA, then apply Wilder's recursive average."""
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = np.flatnonzero(values.rolling(length).mean().notna().to_numpy())
    if not len(valid):
        return result
    offset = int(valid[0])
    seeded = values.iloc[offset:].astype(float).copy()
    seeded.iloc[0] = values.iloc[offset - length + 1 : offset + 1].mean()
    result.iloc[offset:] = seeded.ewm(alpha=1 / length, adjust=False).mean()
    return result


def add_ema_pivot_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame
    out["EMA_26"] = out["close"].ewm(span=26, adjust=False).mean()
    out["EMA_RESEARCH_BARS"] = np.arange(1, len(out) + 1)
    delta = out["close"].diff()
    gain, loss = (
        wilder_average(delta.clip(lower=0)),
        wilder_average(-delta.clip(upper=0)),
    )
    out["RSI_WILDER_14"] = (100 - 100 / (1 + gain / loss)).where(
        (gain != 0) | (loss != 0), 50.0
    )
    true_range = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - out["close"].shift()).abs(),
            (out["low"] - out["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["ATR_WILDER_14"] = wilder_average(true_range)
    out["VOL_SMA_20_PREV"] = out["volume"].shift().rolling(20).mean()
    for period in ("DAY", "WEEK", "MONTH"):
        for level in ("P", "R1", "R2", "S1", "S2"):
            out[f"TRAD_{period}_{level}"] = np.nan
    if (
        not isinstance(out.index, pd.DatetimeIndex)
        or out.index.hasnans
        or out.index.has_duplicates
        or not out.index.is_monotonic_increasing
    ):
        return out
    local = (
        out.index.tz_localize("Asia/Kolkata")
        if out.index.tz is None
        else out.index.tz_convert("Asia/Kolkata")
    )
    dates = local.tz_localize(None)
    for period, frequency in (("DAY", "D"), ("WEEK", "W-SUN"), ("MONTH", "M")):
        keys = dates.to_period(frequency)
        grouped = out.groupby(keys, sort=True).agg(
            high=("high", "max"), low=("low", "min"), close=("close", "last")
        )
        # The first observed group may be a truncated reference period.
        grouped.iloc[0] = np.nan
        if period == "DAY" and any(local.hour * 60 + local.minute != 0):
            # NSE normal-session 15-minute references must contain all 25 bars.
            counts = pd.Series(1, index=keys).groupby(level=0).sum()
            starts = (
                pd.Series(local.hour * 60 + local.minute, index=keys)
                .groupby(level=0)
                .min()
            )
            ends = (
                pd.Series(local.hour * 60 + local.minute, index=keys)
                .groupby(level=0)
                .max()
            )
            grouped.loc[(counts != 25) | (starts != 555) | (ends != 915)] = np.nan
        # Look up the immediately preceding observed period, including invalid
        # periods. Never fall back to an older valid period after missing data.
        prior_groups = grouped.shift()
        if period != "DAY":
            consecutive = pd.Series(grouped.index.asi8, index=grouped.index).diff() == 1
            prior_groups.loc[~consecutive] = np.nan
        prior = prior_groups.reindex(keys)
        high, low, close = (prior[name].to_numpy() for name in ("high", "low", "close"))
        pivot = (high + low + close) / 3
        for level, values in {
            "P": pivot,
            "R1": 2 * pivot - low,
            "R2": pivot + high - low,
            "S1": 2 * pivot - high,
            "S2": pivot - high + low,
        }.items():
            out[f"TRAD_{period}_{level}"] = values
    return out
