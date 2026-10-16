from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.market_day_service import MarketDayService


IST = ZoneInfo("Asia/Kolkata")


def at(hour, minute, *, day=16):
    return datetime(
        2026,
        10,
        day,
        hour,
        minute,
        tzinfo=IST,
    )


def test_weekday_session_phases():
    assert MarketDayService.session(
        now=at(8, 45)
    )["phase"] == "pre_market"

    open_session = MarketDayService.session(
        now=at(9, 15)
    )
    assert open_session["market_open"] is True
    assert open_session["paper_entries_allowed"] is True
    assert open_session["phase"] == "market_open_paper_entry"

    exit_only = MarketDayService.session(
        now=at(15, 0)
    )
    assert exit_only["market_open"] is True
    assert exit_only["paper_entries_allowed"] is False
    assert exit_only["paper_exit_only"] is True

    closed = MarketDayService.session(
        now=at(15, 30)
    )
    assert closed["phase"] == "post_market"
    assert closed["market_open"] is False


def test_weekend_is_non_market_day():
    # 2026-10-17 is Saturday.
    result = MarketDayService.session(
        now=at(10, 0, day=17)
    )

    assert result["market_day"] is False
    assert result["reason"] == "weekend"
    assert result["phase"] == "closed_non_market_day"


def test_configured_holiday_overrides_weekday():
    result = MarketDayService.session(
        now=at(10, 0),
        holiday_dates=["2026-10-16"],
    )

    assert result["market_day"] is False
    assert result["reason"] == "configured_holiday"


def test_special_trading_day_overrides_weekend():
    result = MarketDayService.session(
        now=at(10, 0, day=17),
        special_trading_dates=["2026-10-17"],
    )

    assert result["market_day"] is True
    assert result["reason"] == "special_trading_day"
    assert result["paper_entries_allowed"] is True


def test_invalid_calendar_date_is_rejected():
    try:
        MarketDayService.session(
            now=at(10, 0),
            holiday_dates=["2026-99-99"],
        )
    except ValueError as exc:
        assert "invalid date" in str(exc)
    else:
        raise AssertionError("invalid date must fail")
