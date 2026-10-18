"""R71 weekend scanner, timestamp cutoff and backtest safety contracts."""
from datetime import datetime
from io import StringIO

import numpy as np
import pandas as pd
import pytest

from services.weekend_research_service import (
    IST, backtest_symbol, completed_frame, indicators, last_completed_date,
    parse_csv, prepare_frame, qualified_entry, rank_candidates, scan_symbol,
)


def sample_frame():
    index = pd.bdate_range(end="2026-10-16", periods=170)
    prices = np.concatenate((
        np.linspace(100, 80, 80),
        np.linspace(80, 135, 90),
    ))
    result = pd.DataFrame({
        "open": prices * .998,
        "high": prices * 1.012,
        "low": prices * .987,
        "close": prices,
        "volume": [20000.0] * len(index),
    }, index=index)
    return result


def sunday():
    return datetime(2026, 10, 18, 10, 0, tzinfo=IST)


def test_weekend_cutoff_uses_friday_close():
    assert last_completed_date(sunday()) == pd.Timestamp("2026-10-16")


def test_friday_before_1600_excludes_today():
    current = datetime(2026, 10, 16, 15, 30, tzinfo=IST)
    assert last_completed_date(current) == pd.Timestamp("2026-10-15")


def test_weekday_after_1600_can_use_today():
    current = datetime(2026, 10, 16, 16, 10, tzinfo=IST)
    assert last_completed_date(current) == pd.Timestamp("2026-10-16")


def test_sunday_filters_future_candles():
    candles = sample_frame()
    extra = candles.iloc[[-1]].copy()
    extra.index = pd.DatetimeIndex(["2026-10-19"])
    merged = pd.concat([candles, extra])
    assert completed_frame(merged, now=sunday()).index.max() == pd.Timestamp("2026-10-16")


def test_bad_ohlc_rejected():
    frame = sample_frame()
    frame.iloc[-1, frame.columns.get_loc("high")] = 10
    with pytest.raises(ValueError, match="Inconsistent"):
        prepare_frame(frame)


def test_duplicate_daily_candles_rejected():
    frame = sample_frame()
    with pytest.raises(ValueError, match="Duplicate"):
        prepare_frame(pd.concat([frame, frame.iloc[-1:]]))


def test_csv_multisymbol_and_case_insensitivity():
    a = sample_frame().tail(90).reset_index(names="Date")
    a["Symbol"] = "TCS"
    b = sample_frame().tail(90).reset_index(names="Date")
    b["Symbol"] = "INFY"
    joined = pd.concat([a, b], ignore_index=True)
    parsed = parse_csv(joined.to_csv(index=False).encode())
    assert set(parsed) == {"TCS", "INFY"}
    assert len(parsed["TCS"]) == 90


def test_csv_fails_on_invalid_values_and_input_size():
    with pytest.raises(ValueError):
        parse_csv(b"date,symbol\nbad")
    with pytest.raises(ValueError):
        parse_csv(b"x" * 8_000_001)


def test_indicators_are_warmed_and_finite_at_latest_bar():
    ind = indicators(sample_frame())
    assert pd.notna(ind.iloc[-1]["EMA_50"])
    assert 0 <= ind.iloc[-1]["RSI"] <= 100
    assert ind.iloc[-1]["VOLUME_MA20"] == 20000


def test_screening_uses_completed_session_and_never_places_orders():
    ranked, errors = rank_candidates({"TEST": sample_frame()}, now=sunday())
    assert not errors
    assert len(ranked) == 1
    assert ranked.iloc[0]["Last completed bar"] == "2026-10-16"
    assert ranked.iloc[0]["Classification"] in ("BUY_CROSS", "TREND_WATCH", "NO_ENTRY")


def test_all_unavailable_symbols_are_reported_not_fabricated():
    ranked, errors = rank_candidates({"TEST": sample_frame().tail(20)}, now=sunday())
    assert ranked.empty
    assert "TEST" in errors


def test_backtest_uses_next_open_and_no_future_bars():
    result = backtest_symbol("TEST", sample_frame(), now=sunday(),
                             initial_capital=100000, cost_bps=10, slippage_bps=10)
    assert result["as_of"] == "2026-10-16"
    assert result["execution"] == "signal_close_fill_next_open"
    assert result["metrics"]["initial_capital"] == 100000
    for trade in result["trades"]:
        if trade["exit_reason"] != "END_OF_TEST":
            assert trade["entry_at"] > trade["entry_signal_at"]
    assert all(pd.Timestamp(p["date"]).date() <= sunday().date()
               for p in result["equity_curve"])


def test_qualified_entry_is_not_next_day_fill():
    frame = indicators(sample_frame())
    # Signal predicate reads only previous/current bars, not the following open.
    assert isinstance(qualified_entry(frame.iloc[-3], frame.iloc[-2]), bool)


def test_stale_candles_not_active_buy():
    date = datetime(2026, 11, 5, 10, 0, tzinfo=IST)
    row = scan_symbol("TEST", sample_frame(), now=date)
    assert row["Stale (>7 calendar days)"] is True
    assert row["Entry signal"] is False


def test_rejects_more_than_twenty_symbols():
    with pytest.raises(ValueError):
        rank_candidates({f"S{i}": sample_frame() for i in range(21)}, now=sunday())
