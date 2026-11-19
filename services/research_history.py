"""Warm-up outside evaluation windows and observed 09:30 daily entry prices."""

import pandas as pd


def cutoff(as_of, period):
    stamp = pd.Timestamp(as_of)
    stamp = (
        stamp.tz_localize("Asia/Kolkata")
        if stamp.tzinfo is None
        else stamp.tz_convert("Asia/Kolkata")
    )
    offset = (
        pd.Timedelta(days=int(period[:-1]))
        if period.endswith("d")
        else pd.DateOffset(months=int(period[:-2]))
        if period.endswith("mo")
        else pd.DateOffset(years=int(period[:-1]))
    )
    return (stamp - offset).normalize()


def fetch_days(as_of, period, interval):
    start = cutoff(as_of, period)
    if interval == "1d":
        # Include the entire prior reference year and a preceding partial year;
        # annual_levels deliberately refuses the first observed year.
        seed = min(
            start - pd.Timedelta(days=400),
            pd.Timestamp(year=start.year - 1, month=1, day=1, tz="Asia/Kolkata")
            - pd.Timedelta(days=14),
        )
    else:
        seed = start - pd.Timedelta(days=70)
    return (pd.Timestamp(as_of).tz_convert("Asia/Kolkata").normalize() - seed).days + 1


def entry_sessions(frame):
    """Aggregate only observed 15-minute bars at/after 09:30, never daily opens."""
    local = (
        frame.index.tz_localize("Asia/Kolkata")
        if frame.index.tz is None
        else frame.index.tz_convert("Asia/Kolkata")
    )
    selected = frame.copy(deep=False)
    selected.index = local
    selected = selected.loc[
        (local.hour * 60 + local.minute >= 570)
        & (local.hour * 60 + local.minute <= 915)
    ]
    rows = []
    for day, group in selected.groupby(selected.index.normalize()):
        opening = group.loc[(group.index.hour == 9) & (group.index.minute == 30)]
        # Reject a session with a missing entry quote or incomplete remaining
        # OHLC; a missing first-day high/low must not manufacture a fill.
        expected = pd.date_range(
            day + pd.Timedelta(hours=9, minutes=30),
            day + pd.Timedelta(hours=15, minutes=15),
            freq="15min",
        )
        if opening.empty or not expected.isin(group.index).all():
            continue
        rows.append(
            dict(
                date=day,
                open=float(opening.open.iloc[0]),
                high=float(group.high.max()),
                low=float(group.low.min()),
                close=float(group.close.iloc[-1]),
            )
        )
    return (
        pd.DataFrame(rows).set_index("date")
        if rows
        else pd.DataFrame(
            columns=["open", "high", "low", "close"],
            index=pd.DatetimeIndex([], tz="Asia/Kolkata"),
        )
    )
