"""Recover only genuine prior-day pivot inputs; never fabricate intraday bars."""

from datetime import timedelta

import pandas as pd
import pytest

from indicators.daily_reference import (
    REFERENCE,
    attach_daily_reference,
    needs_daily_reference,
)
from indicators.ema_pivot import add_ema_pivot_indicators
from providers.kite_provider import KiteProvider
from providers.market_data_adapter import MarketDataAdapter

LEVELS = ["TRAD_DAY_" + name for name in ("P", "R1", "R2", "S1", "S2")]


@pytest.fixture
def history():
    days = pd.bdate_range("2026-11-02", periods=3, tz="Asia/Kolkata")
    stamps = [
        day.to_pydatetime() + timedelta(minutes=555 + 15 * i)
        for day in days
        for i in range(24)
    ]
    primary = pd.DataFrame(
        {"Open": 100.0, "High": 103.0, "Low": 98.0, "Close": 101.0, "Volume": 100.0},
        index=pd.DatetimeIndex(stamps),
    )
    daily = pd.DataFrame(
        {"Open": 110.0, "High": 120.0, "Low": 100.0, "Close": 110.0, "Volume": 10000.0},
        index=days,
    )
    return primary, daily


def calculate(primary, daily, *, now="2026-11-04T22:00:00+05:30"):
    attached = attach_daily_reference(primary, daily, now=now)
    return add_ema_pivot_indicators(MarketDataAdapter._normalize("EXAMPLE", attached))


def test_daily_ohlc_completes_all_five_levels_without_adding_a_candle(history):
    primary, daily = history
    original = primary.copy(deep=True)
    assert needs_daily_reference(primary)
    assert (
        add_ema_pivot_indicators(primary.rename(columns=str.lower))
        .iloc[-1][LEVELS]
        .isna()
        .all()
    )
    result = calculate(primary, daily)
    assert result.iloc[-1][LEVELS].tolist() == pytest.approx([110, 120, 130, 100, 90])
    assert result.index.equals(primary.index)
    pd.testing.assert_frame_equal(
        result[[name.lower() for name in primary.columns]],
        primary.rename(columns=str.lower),
    )
    pd.testing.assert_frame_equal(primary, original)
    assert (
        result.attrs["daily_pivot_reference_applied"]["source"]
        == "kite_completed_daily"
    )
    assert result[LEVELS].iloc[:24].isna().all().all()


def test_current_and_future_daily_prices_cannot_change_a_prior_reference(history):
    primary, daily = history
    expected = calculate(primary, daily)
    daily.loc[daily.index[-1], ["Open", "High", "Low", "Close"]] = [
        9000,
        9999,
        8000,
        9500,
    ]
    future = pd.DataFrame(
        {
            "Open": 9000.0,
            "High": 9999.0,
            "Low": 8000.0,
            "Close": 9500.0,
            "Volume": 100.0,
        },
        index=pd.DatetimeIndex([daily.index[-1] + timedelta(days=1)]),
    )
    later = pd.concat([daily, future])
    result = calculate(primary, later, now="2026-11-06T22:00:00+05:30")
    pd.testing.assert_frame_equal(result[LEVELS], expected[LEVELS])


def test_a_forming_daily_candle_is_not_attached(history):
    primary, daily = history
    attached = attach_daily_reference(primary, daily, now="2026-11-03T12:00:00+05:30")
    assert [r["session"] for r in attached.attrs[REFERENCE]["sessions"]] == [
        "2026-11-02"
    ]
    result = add_ema_pivot_indicators(MarketDataAdapter._normalize("EXAMPLE", attached))
    assert result.iloc[-1][LEVELS].isna().all()


@pytest.mark.parametrize(
    "field,value", [("High", 90), ("Close", float("nan")), ("Low", 0), ("Volume", -1)]
)
def test_invalid_exact_day_never_uses_an_older_valid_daily_bar(history, field, value):
    primary, daily = history
    daily.loc[daily.index[1], field] = value
    assert calculate(primary, daily).iloc[-1][LEVELS].isna().all()


def test_missing_exact_reference_day_stays_unknown(history):
    primary, daily = history
    assert calculate(primary, daily.drop(daily.index[1])).iloc[-1][LEVELS].isna().all()


def test_daily_data_exposes_a_whole_missing_intraday_session(history):
    primary, daily = history
    primary = primary.loc[primary.index.normalize() != daily.index[1]]
    assert calculate(primary, daily).iloc[-1][LEVELS].isna().all()


def test_duplicate_daily_session_is_invalid(history):
    primary, daily = history
    duplicate = daily.iloc[[1]].copy()
    duplicate.index = duplicate.index + timedelta(hours=1)
    daily = pd.concat([daily, duplicate]).sort_index()
    assert calculate(primary, daily).iloc[-1][LEVELS].isna().all()


def test_complete_intraday_reference_is_preserved(history):
    primary, daily = history
    closing = primary.loc[primary.index.hour == 15].copy()
    closing.index = closing.index + timedelta(minutes=15)
    complete = pd.concat([primary, closing]).sort_index()
    assert not needs_daily_reference(complete)
    expected = add_ema_pivot_indicators(complete.rename(columns=str.lower))
    actual = calculate(complete, daily)
    pd.testing.assert_frame_equal(actual[LEVELS], expected[LEVELS])


def test_utc_primary_and_daily_timestamps_produce_identical_levels(history):
    primary, daily = history
    expected = calculate(primary, daily)
    actual = calculate(primary.tz_convert("UTC"), daily.tz_convert("UTC"))
    pd.testing.assert_frame_equal(
        actual[LEVELS].tz_convert("Asia/Kolkata"), expected[LEVELS]
    )


def test_kite_provider_fetches_one_daily_reference_and_preserves_observed_bars(history):
    primary, daily = history
    provider = object.__new__(KiteProvider)
    provider.access_token = "synthetic-only"
    provider.instrument_token_for_symbol = lambda symbol: 123
    end = pd.Timestamp("2026-11-04T22:00:00+05:30")
    provider._history_window = lambda period: (daily.index[0], end)
    provider._pace_history = lambda: None
    calls = []

    def fetch(token, start, finish, interval, **kwargs):
        calls.append(interval)
        frame = daily if interval == "day" else primary
        return [
            {"date": stamp, **{name.lower(): row[name] for name in frame.columns}}
            for stamp, row in frame.iterrows()
        ]

    provider.safe_historical = fetch
    result = provider.candles("EXAMPLE", period="30d", interval="15m")
    assert calls == ["15minute", "day"]
    assert len(result) == len(primary)
    calculated = add_ema_pivot_indicators(
        MarketDataAdapter._normalize("EXAMPLE", result)
    )
    assert calculated.iloc[-1][LEVELS].tolist() == pytest.approx(
        [110, 120, 130, 100, 90]
    )
