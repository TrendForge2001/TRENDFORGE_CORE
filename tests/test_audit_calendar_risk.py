"""Holiday freshness, frozen research calendars and default account limits."""

import json
import os
import sqlite3
from datetime import date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from indicators.approved_strategies import add_native
from scanner import approved_strategies as rules
from scanner.strategy_registry import list_strategies
from services.market_day_service import MarketDayService
from services.paper_admission_policy import admit, capture, fingerprint
from services.paper_auto_entry_service import PaperAutoEntryService
from services.staged_paper_execution import StagedPaperExecution
from services.technical_trading_service import TechnicalTradingService
from services.trading_calendar import (
    NSE_2026_HOLIDAYS,
    configured_calendar,
    is_market_day,
    latest_completed_session,
)
from tests.test_aligned_research_policy import book as book_fixture
from tests.test_aligned_research_policy import flat_state
from tests.test_approved_horizon_strategies import pair

IST = ZoneInfo("Asia/Kolkata")
HOLIDAY = "2026-11-10"


def save_calendar(path, calendar):
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS settings "
            "(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
        )
        db.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)",
            (
                "operations.policy.r69_0",
                json.dumps({"calendar": calendar}),
            ),
        )


@pytest.fixture
def holiday_calendar(tmp_path, monkeypatch):
    path = tmp_path / "calendar.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    value = {"holiday_dates": [HOLIDAY], "special_trading_dates": []}
    save_calendar(path, value)
    return path


@pytest.mark.parametrize("hour", [8, 14, 16])
def test_completed_daily_freshness_skips_configured_weekday_holiday(
    holiday_calendar, hour
):
    now = datetime(2026, 11, 11, hour, tzinfo=IST)
    expected = "2026-11-09" if hour < 16 else "2026-11-11"
    frame = pd.DataFrame({"close": [100.0]}, index=pd.DatetimeIndex([expected], tz=IST))
    assert (
        TechnicalTradingService._execution_block_reason(frame, mode="swing", now=now)
        is None
    )
    frame.index = pd.DatetimeIndex([HOLIDAY], tz=IST)
    assert (
        TechnicalTradingService._execution_block_reason(frame, mode="swing", now=now)
        == "stale_candles"
    )


def test_holiday_does_not_complete_a_fictitious_daily_bar(holiday_calendar):
    frame = pd.DataFrame(
        {"close": [100.0]}, index=pd.DatetimeIndex(["2026-11-09"], tz=IST)
    )
    now = datetime(2026, 11, 10, 16, tzinfo=IST)
    assert (
        TechnicalTradingService._execution_block_reason(frame, mode="swing", now=now)
        is None
    )
    assert not is_market_day(now)
    intraday = frame.copy()
    intraday.index = pd.DatetimeIndex(["2026-11-10 09:45"], tz=IST)
    assert (
        TechnicalTradingService._execution_block_reason(
            intraday, mode="intraday", now=now
        )
        == "intraday_entry_window_closed"
    )


def test_staged_daily_entry_advances_to_the_next_actual_session(holiday_calendar):
    start, end = StagedPaperExecution.window("2026-11-09T00:00:00+05:30", "swing")
    assert start == datetime(2026, 11, 11, 9, 15, tzinfo=IST)
    assert end == datetime(2026, 11, 11, 15, 30, tzinfo=IST)


def test_previous_and_next_sessions_handle_weekends_and_explicit_special_dates():
    special = ["2026-11-08"]
    assert MarketDayService.previous_session_date(
        date(2026, 11, 9), special=special
    ) == date(2026, 11, 8)
    assert MarketDayService.next_session_date(
        date(2026, 11, 6), special=special
    ) == date(2026, 11, 8)
    assert MarketDayService.last_completed_session_date(
        datetime(2026, 11, 8, 16, tzinfo=IST), special=special
    ) == date(2026, 11, 8)
    assert MarketDayService.last_completed_session_date(
        datetime(2026, 11, 9, 15, 45, tzinfo=IST), close_time=time(16)
    ) == date(2026, 11, 6)


def test_absent_calendar_reads_do_not_create_a_database(tmp_path, monkeypatch):
    path = tmp_path / "absent.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    assert configured_calendar() == {
        "holiday_dates": list(NSE_2026_HOLIDAYS),
        "special_trading_dates": [],
    }
    assert not path.exists()


@pytest.mark.parametrize(
    "stored", [None, {"holiday_dates": [], "special_trading_dates": []}]
)
def test_published_november_holiday_is_used_without_operator_configuration(
    tmp_path, monkeypatch, stored
):
    path = tmp_path / "calendar.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    if stored is not None:
        save_calendar(path, stored)
    now = datetime(2026, 11, 25, 11, 30, tzinfo=IST)
    assert latest_completed_session(now) == date(2026, 11, 23)
    frame = pd.DataFrame(
        {"close": [100]}, index=pd.DatetimeIndex(["2026-11-23"], tz=IST)
    )
    assert (
        TechnicalTradingService._execution_block_reason(frame, mode="swing", now=now)
        is None
    )
    frame.index = pd.DatetimeIndex(["2026-11-20"], tz=IST)
    assert (
        TechnicalTradingService._execution_block_reason(frame, mode="swing", now=now)
        == "stale_candles"
    )
    assert latest_completed_session(now.replace(hour=16)) == date(2026, 11, 25)
    assert not is_market_day(datetime(2026, 11, 24, 11, tzinfo=IST))


def test_explicit_special_session_overrides_published_holiday(tmp_path, monkeypatch):
    path = tmp_path / "calendar.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    save_calendar(
        path, {"holiday_dates": ["2026-11-12"], "special_trading_dates": ["2026-11-24"]}
    )
    calendar = configured_calendar()
    assert "2026-11-12" in calendar["holiday_dates"]
    assert "2026-11-24" not in calendar["holiday_dates"]
    assert latest_completed_session(datetime(2026, 11, 25, 11, tzinfo=IST)) == date(
        2026, 11, 24
    )


def test_stale_scan_signals_are_not_presented_as_current_entries():
    from webapp.scanner_results import stock_view

    rows = [{"symbol": "EXAMPLE", "signal": "EXIT", "data_status": "STALE"}]
    result = stock_view(rows)
    assert result.iloc[0]["Technical signal"] == "WAIT · stale candles"
    assert rows[0]["signal"] == "EXIT"  # Original audit evidence remains intact.
    assert pd.isna(result.iloc[0]["Rating /100"])


def test_corrupt_calendar_blocks_live_entries_instead_of_assuming_weekday(
    holiday_calendar,
):
    save_calendar(
        holiday_calendar, {"holiday_dates": ["invalid"], "special_trading_dates": []}
    )
    assert not is_market_day(datetime(2026, 11, 11, 10, tzinfo=IST))
    with pytest.raises(ValueError, match="unavailable"):
        configured_calendar()


@pytest.fixture
def paper_book(tmp_path, monkeypatch):
    yield from book_fixture.__wrapped__(tmp_path, monkeypatch)


def test_calendar_is_frozen_in_admission_policy_and_changes_its_fingerprint(paper_book):
    path = paper_book.path / "paper.db"
    before = capture(paper_book.auto)
    save_calendar(path, {"holiday_dates": ["2026-11-12"], "special_trading_dates": []})
    frozen = capture(paper_book.auto)
    assert fingerprint(before) != fingerprint(frozen)
    save_calendar(path, {"holiday_dates": [], "special_trading_dates": []})
    key, context, _, row = pair(1)
    plan = rules.plan_for(key, row, context)
    result = admit(
        frozen,
        plan=plan,
        score=100,
        confidence=90,
        now=datetime(2026, 11, 12, 10, tzinfo=IST),
        state=flat_state(),
    )
    assert "outside_nse_entry_window" in result["reasons"]
    assert not result["approved"]


def test_every_launch_uses_policy_file_risk_defaults(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith("TRENDFORGE_PAPER_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "absent.db"))
    trades = SimpleNamespace(
        entries_for_date=lambda _: 0, realized_pnl_for_entry_date=lambda _: 0
    )
    runtime = SimpleNamespace(trades=trades, portfolio=SimpleNamespace(positions={}))
    auto = PaperAutoEntryService(SimpleNamespace(runtime=runtime))
    assert auto.enabled is False
    assert (
        auto.max_open_positions,
        auto.max_daily_entries,
        auto.max_daily_loss_percent,
    ) == (3, 6, 3)
    assert auto.daily_loss_basis == "realized_plus_unrealized"
    assert auto.cash_reserve == 0
    runtime.portfolio.positions["ABC"] = SimpleNamespace(pnl=-3100)
    status = auto.account_entry_limits(datetime(2026, 11, 11, 10, tzinfo=IST))
    assert "maximum_daily_loss_reached" in status["reasons"]
    runtime.portfolio.positions.clear()
    trades.entries_for_date = lambda _: 6
    assert (
        "maximum_daily_entries_reached"
        in auto.account_entry_limits(datetime(2026, 11, 11, 10, tzinfo=IST))["reasons"]
    )


def test_current_public_rsi_contract_is_wilder_and_matches_independent_recursion():
    assert all("RSI_14" not in row["indicators"] for row in list_strategies())
    prices = 100 + np.arange(90) * 0.1 + np.sin(np.arange(90) * 0.7) * 3
    frame = pd.DataFrame(
        dict(
            close=prices,
            high=prices + 1,
            low=prices - 1,
            open=prices,
            volume=1000.0,
            RSI_14=0.0,
        )
    )
    output = add_native(frame)["RSI_WILDER_14"]
    delta = np.diff(prices)
    gain, loss = np.maximum(delta, 0), np.maximum(-delta, 0)
    a, b = gain[:14].mean(), loss[:14].mean()
    expected = [100 * a / (a + b)]
    for i in range(14, len(delta)):
        a, b = (13 * a + gain[i]) / 14, (13 * b + loss[i]) / 14
        expected.append(100 * a / (a + b))
    np.testing.assert_allclose(output.iloc[14:], expected, rtol=0, atol=1e-12)


def test_render_validation_caps_provider_batches_without_dropping_symbols(
    paper_book, monkeypatch
):
    from indicators.indicator_engine import IndicatorEngine
    from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner
    from services.multi_strategy_validation_service import (
        MultiStrategyValidationService,
    )

    monkeypatch.setenv("RENDER", "true")
    end = pd.Timestamp("2026-11-18 15:30", tz=IST)
    days = pd.date_range(pd.Timestamp("2019-01-01", tz=IST), end.normalize(), freq="B")
    index = pd.DatetimeIndex(
        [
            day + pd.Timedelta(hours=9, minutes=15 + 15 * i)
            for day in days[-85:]
            for i in range(25)
        ]
    )

    def frame(index):
        return pd.DataFrame(
            dict(open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0),
            index=index,
        )

    daily, native = frame(days), frame(index)
    symbols = [f"SAMPLE{i}" for i in range(13)]
    batches = []

    def fetch(requested, *, period, interval):
        batches.append((list(requested), interval))
        return {
            s: (daily if interval == "1d" else native).copy() for s in requested
        }, {}

    scanner = MultiStrategyNiftyScanner(
        market_data=SimpleNamespace(batch_candles_with_errors=fetch),
        indicator_engine=IndicatorEngine(),
        universe_provider=SimpleNamespace(
            load=lambda *a, **k: {"members": [{"symbol": s} for s in symbols]}
        ),
    )
    result = MultiStrategyValidationService(scanner_service=scanner).run(
        modes=["swing"],
        universes=["NIFTY 500"],
        strategy_ids=[rules.IDS[2]],
        chunk_size=50,
        limit=None,
        evaluation_as_of=end.isoformat(),
    )
    assert not result["errors"]
    assert len(result["backtest_results"]) == 13
    assert max(len(batch) for batch, _ in batches) <= 5
    assert set(
        s for batch, interval in batches if interval == "1d" for s in batch
    ) == set(symbols)
