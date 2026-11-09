"""Missing candles remain blocked unless complete broker sub-bars recover them."""

import math
from datetime import timedelta

import pandas as pd
import pytest

from indicators.ema_pivot import add_ema_pivot_indicators
from providers.candle_repair import missing_quarter_hours, repair_quarter_hours
from providers.kite_provider import KiteProvider

START = pd.Timestamp("2026-11-02", tz="Asia/Kolkata")
END = pd.Timestamp("2026-11-09 12:00", tz="Asia/Kolkata")
MISSING = pd.Timestamp("2026-11-06 15:15", tz="Asia/Kolkata")
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


@pytest.fixture
def history():
    days = pd.bdate_range("2026-11-02", periods=5, tz="Asia/Kolkata")
    stamps = [
        day.to_pydatetime() + timedelta(minutes=555 + 15 * offset)
        for day in days
        for offset in range(25)
    ]
    stamps += [
        END.normalize().to_pydatetime() + timedelta(minutes=555 + 15 * offset)
        for offset in range(11)
    ]
    complete = pd.DataFrame(
        [[100.0, 103.0, 98.0, 101.0, 30.0]] * len(stamps),
        index=pd.DatetimeIndex(stamps),
        columns=FIELDS,
    )
    complete.loc[MISSING] = [100, 110, 99, 109, 33]
    sub_bars = pd.DataFrame(
        [[100, 105, 99, 104, 10], [104, 106, 103, 105, 11], [105, 110, 104, 109, 12]],
        columns=FIELDS,
        index=pd.date_range(MISSING, periods=3, freq="5min"),
        dtype=float,
    )
    return complete, complete.drop(MISSING), sub_bars


def pivots(frame):
    return add_ema_pivot_indicators(frame.rename(columns=str.lower).copy())[
        ["TRAD_DAY_P", "TRAD_DAY_R1", "TRAD_DAY_R2", "TRAD_DAY_S1", "TRAD_DAY_S2"]
    ]


def test_complete_observed_triplet_restores_exact_candle_and_all_five_pivots(history):
    complete, primary, sub_bars = history
    original = primary.copy(deep=True)
    assert pivots(primary).iloc[-1].isna().all()
    repaired = repair_quarter_hours(primary, sub_bars, start=START, end=END)
    pd.testing.assert_frame_equal(repaired, complete)
    pd.testing.assert_frame_equal(pivots(repaired), pivots(complete))
    assert all(math.isfinite(value) for value in pivots(repaired).iloc[-1])
    pd.testing.assert_frame_equal(primary, original)
    assert repaired.attrs["history_repair"]["repaired_bars"] == 1


@pytest.mark.parametrize(
    "damage", ["missing", "nan", "negative_volume", "bad_ohlc", "overflow"]
)
def test_incomplete_or_invalid_triplet_never_fills_a_gap(history, damage):
    _, primary, sub_bars = history
    if damage == "missing":
        sub_bars = sub_bars.iloc[:2]
    elif damage == "nan":
        sub_bars.iloc[1, 3] = float("nan")
    elif damage == "negative_volume":
        sub_bars.iloc[1, 4] = -1
    elif damage == "overflow":
        sub_bars["Volume"] = 1e308
    else:
        sub_bars.iloc[1, 1] = 1
    repaired = repair_quarter_hours(primary, sub_bars, start=START, end=END)
    assert MISSING not in repaired.index
    assert pivots(repaired).iloc[-1].isna().all()


def test_timezone_equivalence_and_no_replacement_of_observed_bars(history):
    complete, primary, sub_bars = history
    primary.index = primary.index.tz_convert("UTC")
    sub_bars.index = sub_bars.index.tz_convert("UTC")
    repaired = repair_quarter_hours(primary, sub_bars, start=START, end=END)
    pd.testing.assert_frame_equal(repaired.tz_convert("Asia/Kolkata"), complete)
    sub_bars["High"] = 999
    unchanged = repair_quarter_hours(complete, sub_bars, start=START, end=END)
    pd.testing.assert_frame_equal(unchanged, complete)


def test_request_bounds_do_not_add_forming_bars_or_invent_absent_days(history):
    _, primary, _ = history
    primary = primary.loc[
        primary.index.normalize() != START.to_pydatetime() + timedelta(days=1)
    ]
    missing = missing_quarter_hours(primary, start=START, end=END)
    assert missing == [MISSING]
    assert END not in missing
    assert missing_quarter_hours(primary, start=END, end=END) == []


def as_rows(frame):
    return [
        {"date": stamp, **{name.lower(): row[name] for name in FIELDS}}
        for stamp, row in frame.iterrows()
    ]


@pytest.mark.parametrize("case", ["recovered", "unavailable", "already_complete"])
def test_provider_makes_one_paced_bounded_read_and_preserves_primary_on_failure(
    history, case
):
    complete, primary, sub_bars = history
    provider = object.__new__(KiteProvider)
    provider.access_token = "synthetic-only"
    provider.instrument_token_for_symbol = lambda symbol: 123
    provider._history_window = lambda period: (START, END)
    calls, pacing = [], []
    provider._pace_history = lambda: pacing.append(True)

    def fetch(token, start, end, interval, **kwargs):
        calls.append((token, start, end, interval))
        if interval == "5minute":
            if case == "unavailable":
                raise RuntimeError("Synthetic unavailable history")
            return as_rows(sub_bars)
        return as_rows(complete if case == "already_complete" else primary)

    provider.safe_historical = fetch
    result = provider.candles("SYNTHETIC", period="60d", interval="15m")
    expected_calls = [(123, START, END, "15minute")]
    if case != "already_complete":
        expected_calls.append((123, START, END, "5minute"))
    assert calls == expected_calls
    assert len(pacing) == len(expected_calls)
    expected = (primary if case == "unavailable" else complete).rename_axis("date")
    pd.testing.assert_frame_equal(result, expected)
    if case == "unavailable":
        assert result.attrs["history_repair"]["status"] == "unavailable"
