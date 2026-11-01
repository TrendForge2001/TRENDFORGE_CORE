"""The backtest alignment error is recovered without fabricated candles."""

import pandas as pd
import pytest

from backtest.history_alignment import align_history
from services.portfolio_backtest_service import PortfolioBacktestService
from tests.test_three_stock_portfolio import STRATEGY, canonical_frame, service
from webapp.portfolio_backtesting import validate_result


def history(size=120):
    index = pd.bdate_range("2026-01-05", periods=size, tz="Asia/Kolkata")
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
            "EMA_RESEARCH_BARS": range(1, size + 1),
        },
        index=index,
    )


def test_uneven_history_boundaries_are_trimmed_to_actual_common_candles():
    raw = history()
    aligned, report = align_history({"A": raw, "B": raw.iloc[20:-5]})
    assert set(aligned) == {"A", "B"} and report["excluded_symbols"] == []
    pd.testing.assert_frame_equal(aligned["A"], raw.iloc[20:-5], check_freq=False)
    pd.testing.assert_frame_equal(aligned["A"], aligned["B"])
    assert aligned["A"]["EMA_RESEARCH_BARS"].iloc[0] == 21


def test_missing_interior_candles_exclude_the_stock_instead_of_hiding_stops():
    raw = history()
    aligned, report = align_history(
        {"A": raw, "B": raw.drop(raw.index[65]), "C": raw.copy()}
    )
    assert set(aligned) == {"A", "C"}
    assert report["excluded_symbols"] == [
        {"symbol": "B", "reason": "interior_candle_calendar_mismatch"}
    ]
    assert aligned["A"].index.equals(raw.index)


def test_recent_listing_does_not_block_stocks_with_enough_history():
    raw = history()
    aligned, report = align_history({"A": raw, "IPO": raw.iloc[-20:]})
    assert list(aligned) == ["A"]
    assert report["excluded_symbols"][0]["symbol"] == "IPO"
    with pytest.raises(ValueError, match="incomplete"):
        align_history({"IPO": raw.iloc[-20:]})


def test_actual_portfolio_service_recovers_the_reported_alignment_error():
    technical = service()
    raw = canonical_frame()
    technical.market_data.batch_candles_with_errors = lambda *a, **k: (
        {"A": raw, "B": raw.iloc[10:]},
        {},
    )
    result = PortfolioBacktestService(technical).run(
        symbols=["A", "B"], mode="swing", strategy_id=STRATEGY
    )
    validate_result(result)
    assert result["status"] == "completed"
    assert result["symbols"] == ["A", "B"]
    assert result["history_alignment"]["bars"] == len(raw) - 10


def test_missing_stock_is_reported_while_other_stocks_backtest():
    technical = service()
    technical.market_data.batch_candles_with_errors = lambda *a, **k: (
        {"A": canonical_frame()},
        {},
    )
    result = PortfolioBacktestService(technical).run(
        symbols=["A", "MISSING"], mode="swing", strategy_id=STRATEGY
    )
    assert result["symbols"] == ["A"]
    assert result["requested_symbols"] == ["A", "MISSING"]
    assert result["history_alignment"]["excluded_symbols"] == [
        {"symbol": "MISSING", "reason": "history_unavailable_or_insufficient"}
    ]
