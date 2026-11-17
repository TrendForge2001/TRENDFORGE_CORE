"""Prior-calendar-year Fibonacci levels from complete daily reference years."""

import numpy as np
import pandas as pd

LEVELS = ("P", "R1", "R2", "R3", "S1", "S2", "S3")


def annual_levels(daily):
    annual = {}
    for offset, (year, group) in enumerate(daily.groupby(daily.index.year)):
        # First observed year can be partial. Coverage is not a calendar audit.
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
            **{f"R{i}": pivot + r * span for i, r in enumerate((0.382, 0.618, 1.0), 1)},
            **{f"S{i}": pivot - r * span for i, r in enumerate((0.382, 0.618, 1.0), 1)},
        }
    return annual


def attach_levels(frame, annual):
    out = frame.copy()
    local = out.index
    if local.tz is not None:
        local = local.tz_convert("Asia/Kolkata")
    for name in LEVELS:
        out["FIB_YEAR_" + name] = [
            annual.get(int(year), {}).get(name, np.nan) for year in local.year
        ]
    return out
