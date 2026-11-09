"""Recover missing quarter-hours only from complete observed Kite sub-bars."""

import math
from datetime import timedelta

import pandas as pd

FIELDS = ("Open", "High", "Low", "Close", "Volume")
TZ = "Asia/Kolkata"


def _local_index(frame):
    index = frame.index
    if (
        not isinstance(index, pd.DatetimeIndex)
        or index.hasnans
        or index.has_duplicates
        or not index.is_monotonic_increasing
    ):
        raise ValueError("Candle repair requires unique chronological timestamps")
    return index.tz_localize(TZ) if index.tz is None else index.tz_convert(TZ)


def _local_stamp(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_localize(TZ) if stamp.tzinfo is None else stamp.tz_convert(TZ)


def missing_quarter_hours(frame, *, start, end):
    """Inspect observed weekdays inside the request, never invent absent days."""
    local = _local_index(frame)
    observed = set(local)
    lower = _local_stamp(start).to_pydatetime()
    upper = _local_stamp(end).to_pydatetime()
    missing = []
    for day in local.normalize().unique():
        day = day.to_pydatetime()
        if day.weekday() >= 5:
            continue
        for offset in range(25):
            stamp = day + timedelta(minutes=555 + 15 * offset)
            if (
                lower <= stamp
                and stamp + timedelta(minutes=15) <= upper
                and stamp not in observed
            ):
                missing.append(stamp)
    return missing


def repair_quarter_hours(primary, sub_bars, *, start, end):
    """Keep every original bar; add only aggregates of three real 5-minute bars."""
    missing = missing_quarter_hours(primary, start=start, end=end)
    observed = sub_bars.loc[:, list(FIELDS)].copy()
    observed.index = _local_index(sub_bars)
    repairs, stamps = [], []
    for stamp in missing:
        component_times = [stamp + timedelta(minutes=5 * n) for n in range(3)]
        if any(value not in observed.index for value in component_times):
            continue
        rows = observed.loc[component_times]
        values = rows.to_numpy(dtype=float)
        if not all(math.isfinite(value) for value in values.flat):
            continue
        if any(
            not (
                0
                < row.Low
                <= min(row.Open, row.Close)
                <= max(row.Open, row.Close)
                <= row.High
            )
            or row.Volume < 0
            for row in rows.itertuples()
        ):
            continue
        try:
            volume = math.fsum(float(value) for value in rows.Volume)
        except OverflowError:
            continue
        repairs.append(
            [
                float(rows.iloc[0].Open),
                float(rows.High.max()),
                float(rows.Low.min()),
                float(rows.iloc[-1].Close),
                volume,
            ]
        )
        stamps.append(stamp)
    if not repairs:
        return primary
    additions = pd.DataFrame(repairs, columns=FIELDS, index=pd.DatetimeIndex(stamps))
    additions.index = (
        additions.index.tz_localize(None)
        if primary.index.tz is None
        else additions.index.tz_convert(primary.index.tz)
    )
    additions.index.name = primary.index.name
    result = pd.concat([primary, additions]).sort_index()
    result.attrs = {
        **primary.attrs,
        "history_repair": {
            "source": "kite_5minute_complete_triplets",
            "repaired_bars": len(stamps),
            "timestamps": [stamp.isoformat() for stamp in stamps],
        },
    }
    return result
