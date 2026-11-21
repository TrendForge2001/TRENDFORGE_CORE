"""Read configured operational dates; frozen historical policies never read SQLite."""

import json
import sqlite3
from contextlib import closing

from core.storage_config import resolve_storage
from services.market_day_service import MarketDayService


class CalendarUnavailable(ValueError):
    pass


def configured_calendar():
    path = resolve_storage().database.resolve()
    empty = {"holiday_dates": [], "special_trading_dates": []}
    if not path.exists():
        return empty
    try:
        with closing(
            sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        ) as db:
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'"
            ).fetchone():
                return empty
            row = db.execute(
                "SELECT value FROM settings WHERE key=?", ("operations.policy.r69_0",)
            ).fetchone()
        if not row:
            return empty
        policy = json.loads(row[0])
        value = policy.get("calendar", empty)
        return normalize_calendar(value)
    except (sqlite3.Error, TypeError, ValueError, AttributeError):
        raise CalendarUnavailable(
            "Configured session calendar is unavailable"
        ) from None


def normalize_calendar(value):
    if not isinstance(value, dict) or set(value) != {
        "holiday_dates",
        "special_trading_dates",
    }:
        raise ValueError("Explicit session calendar required")
    normalized = {
        key: sorted(
            day.isoformat() for day in MarketDayService._dates(dates, field=key)
        )
        for key, dates in value.items()
    }
    if set(normalized["holiday_dates"]) & set(normalized["special_trading_dates"]):
        raise ValueError("Session calendar dates overlap")
    return normalized


def calendar_arguments(calendar):
    return {
        "holidays": calendar["holiday_dates"],
        "special": calendar["special_trading_dates"],
    }


def is_market_day(now):
    try:
        return MarketDayService.is_session_date(
            MarketDayService.local_now(now).date(),
            **calendar_arguments(configured_calendar()),
        )
    except CalendarUnavailable:
        return False


def latest_completed_session(now, *, close_time=None):
    return MarketDayService.last_completed_session_date(
        now, close_time=close_time, **calendar_arguments(configured_calendar())
    )


def next_session(day):
    return MarketDayService.next_session_date(
        day, **calendar_arguments(configured_calendar())
    )
