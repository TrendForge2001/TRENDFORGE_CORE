"""Deterministic NSE session calendar with explicit configured overrides."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo


class MarketDayService:
    MARKET_TZ = ZoneInfo("Asia/Kolkata")
    MARKET_OPEN = time(9, 15)
    PAPER_ENTRY_CUTOFF = time(15, 0)
    MARKET_CLOSE = time(15, 30)

    @staticmethod
    def _dates(
        values: Any,
        *,
        field: str,
    ) -> set[date]:
        if values in (None, ""):
            return set()
        if not isinstance(values, (list, tuple, set)):
            raise ValueError(
                f"{field} must be a list of YYYY-MM-DD dates"
            )
        result: set[date] = set()
        for value in values:
            try:
                result.add(date.fromisoformat(str(value).strip()))
            except ValueError as exc:
                raise ValueError(
                    f"{field} contains invalid date: {value}"
                ) from exc
        return result

    @classmethod
    def local_now(
        cls,
        value: datetime | None = None,
    ) -> datetime:
        current = value or datetime.now(cls.MARKET_TZ)
        if current.tzinfo is None:
            return current.replace(tzinfo=cls.MARKET_TZ)
        return current.astimezone(cls.MARKET_TZ)

    @classmethod
    def session(
        cls,
        *,
        now: datetime | None = None,
        holiday_dates: Any = None,
        special_trading_dates: Any = None,
    ) -> dict[str, Any]:
        current = cls.local_now(now)
        current_date = current.date()
        holidays = cls._dates(
            holiday_dates,
            field="calendar.holiday_dates",
        )
        special = cls._dates(
            special_trading_dates,
            field="calendar.special_trading_dates",
        )

        weekend = current.weekday() >= 5
        if current_date in special:
            market_day = True
            reason = "special_trading_day"
        elif current_date in holidays:
            market_day = False
            reason = "configured_holiday"
        elif weekend:
            market_day = False
            reason = "weekend"
        else:
            market_day = True
            reason = "weekday"

        current_time = current.time().replace(
            second=0,
            microsecond=0,
        )
        if not market_day:
            phase = "closed_non_market_day"
        elif current_time < cls.MARKET_OPEN:
            phase = "pre_market"
        elif current_time < cls.PAPER_ENTRY_CUTOFF:
            phase = "market_open_paper_entry"
        elif current_time < cls.MARKET_CLOSE:
            phase = "market_open_paper_exit_only"
        else:
            phase = "post_market"

        return {
            "status": "ready",
            "timezone": "Asia/Kolkata",
            "now_ist": current.isoformat(),
            "date_ist": current_date.isoformat(),
            "weekday": current.strftime("%A"),
            "market_day": market_day,
            "reason": reason,
            "phase": phase,
            "market_open": (
                market_day
                and cls.MARKET_OPEN <= current_time < cls.MARKET_CLOSE
            ),
            "paper_entries_allowed": (
                market_day
                and cls.MARKET_OPEN <= current_time < cls.PAPER_ENTRY_CUTOFF
            ),
            "paper_exit_only": (
                market_day
                and cls.PAPER_ENTRY_CUTOFF
                <= current_time
                < cls.MARKET_CLOSE
            ),
            "market_open_time_ist": "09:15",
            "paper_entry_cutoff_time_ist": "15:00",
            "market_close_time_ist": "15:30",
            "calendar_authority": (
                "weekday_plus_configured_overrides"
            ),
            "configured_holiday_count": len(holidays),
            "configured_special_trading_day_count": len(special),
        }


__all__ = ["MarketDayService"]
