"""Observed, completed Kite daily candles for missing prior-session pivots."""

from bisect import bisect_left
from datetime import date
from math import isfinite

import pandas as pd

REFERENCE = "kite_completed_daily_reference"
SOURCE = "kite_completed_daily"
LEVELS = ("P", "R1", "R2", "S1", "S2")


def _local(index):
    if (
        not isinstance(index, pd.DatetimeIndex)
        or index.hasnans
        or index.has_duplicates
        or not index.is_monotonic_increasing
    ):
        raise ValueError("Unique chronological candle timestamps are required")
    return (
        index.tz_localize("Asia/Kolkata")
        if index.tz is None
        else index.tz_convert("Asia/Kolkata")
    )


def needs_daily_reference(frame):
    """Detect incomplete observed reference sessions; never invent a missing bar."""
    try:
        local = _local(frame.index)
    except ValueError:
        return False
    if not len(local) or not any(local.hour * 60 + local.minute != 0):
        return False
    sessions = local.normalize()
    for session in sessions.unique()[:-1]:
        stamps = local[sessions == session]
        minutes = stamps.hour * 60 + stamps.minute
        if len(minutes) != 25 or set(minutes) != set(range(555, 916, 15)):
            return True
    return False


def _valid_prices(row):
    try:
        values = [row[name] for name in ("open", "high", "low", "close", "volume")]
        if any(isinstance(value, bool) for value in values):
            return False
        opening, high, low, close, volume = map(float, values)
        return (
            all(isfinite(value) for value in (opening, high, low, close, volume))
            and 0 < low <= min(opening, close) <= max(opening, close) <= high
            and volume >= 0
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def attach_daily_reference(primary, daily, *, now):
    """Attach provenance and valid closed-day OHLC; preserve the primary bars."""
    local = _local(daily.index)
    current = pd.Timestamp(now)
    current = (
        current.tz_localize("Asia/Kolkata")
        if current.tzinfo is None
        else current.tz_convert("Asia/Kolkata")
    )
    frame = daily.rename(columns=str.lower)
    records = {}
    for offset, stamp in enumerate(local):
        session = stamp.date()
        # Today's daily bar is unnecessary for any completed intraday bar's
        # prior-day reference. Exclude it even after the normal close.
        if session >= current.date():
            continue
        key = session.isoformat()
        row = frame.iloc[offset]
        record = {"session": key, "valid": False}
        if key not in records and _valid_prices(row):
            record = {
                "session": key,
                "valid": True,
                **{
                    name: float(row[name])
                    for name in ("open", "high", "low", "close", "volume")
                },
            }
        # A duplicate or invalid latest day remains an explicit invalid marker,
        # so an older good day cannot silently replace it.
        records[key] = record
    result = primary.copy()
    result.attrs[REFERENCE] = {"source": SOURCE, "sessions": list(records.values())}
    return result


def complete_daily_pivots(frame):
    """Use the exact prior observed session only, with no future or stale fallback."""
    payload = frame.attrs.get(REFERENCE)
    if not isinstance(payload, dict) or payload.get("source") != SOURCE:
        return frame
    records = payload.get("sessions")
    if not isinstance(records, list) or len(records) > 5000:
        return frame
    try:
        local = _local(frame.index)
        references = {}
        for row in records:
            if not isinstance(row, dict) or not isinstance(row.get("session"), str):
                return frame
            session = date.fromisoformat(row["session"])
            references[session] = row if session not in references else {"valid": False}
    except (TypeError, ValueError):
        return frame
    ordered = sorted(references)
    dates = local.normalize()
    observed = list(dates.unique())
    columns = ["TRAD_DAY_" + level for level in LEVELS]
    used, targets = set(), set()
    for offset, target in enumerate(observed[1:], 1):
        preceding = local[dates == observed[offset - 1]]
        minutes = preceding.hour * 60 + preceding.minute
        if len(minutes) == 25 and set(minutes) == set(range(555, 916, 15)):
            continue
        reference_date = observed[offset - 1].date()
        before = bisect_left(ordered, target.date()) - 1
        if before < 0 or ordered[before] != reference_date:
            continue
        row = references[reference_date]
        if row.get("valid") is not True or not _valid_prices(row):
            continue
        high, low, close = (float(row[name]) for name in ("high", "low", "close"))
        pivot = high / 3 + low / 3 + close / 3
        values = [
            pivot,
            2 * pivot - low,
            pivot + high - low,
            2 * pivot - high,
            pivot - high + low,
        ]
        if not all(isfinite(value) for value in values):
            continue
        missing = (dates == target) & frame[columns].isna().all(axis=1).to_numpy()
        if missing.any():
            frame.loc[missing, columns] = values
            used.add(reference_date.isoformat())
            targets.add(target.date().isoformat())
    if used:
        frame.attrs["daily_pivot_reference_applied"] = {
            "source": SOURCE,
            "reference_sessions": len(used),
            "latest_reference": max(used),
            "latest_target_session": max(targets),
        }
    return frame
