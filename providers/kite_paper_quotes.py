"""Timestamp-verified Kite quotes for simulated fills and exits."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo


class FreshKitePaperQuotes:
    MARKET_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(self, broker: Any, *, max_age_seconds: float = 60.0):
        self.broker = broker
        if not isfinite(max_age_seconds) or not 1 <= max_age_seconds <= 120:
            raise ValueError("Quote age must be between 1 and 120 seconds")
        self.max_age_seconds = max_age_seconds

    def prices(self, instruments: list[str], *, now: datetime | None = None) -> dict:
        current = now or datetime.now(self.MARKET_TZ)
        current = (
            current.replace(tzinfo=self.MARKET_TZ)
            if current.tzinfo is None
            else current.astimezone(self.MARKET_TZ)
        )
        raw = self.broker.quote(instruments)
        if not isinstance(raw, dict):
            raise ValueError("Kite quote response is unavailable")
        output = {}
        for instrument in instruments:
            row = raw.get(instrument)
            if not isinstance(row, dict):
                raise ValueError("A current Kite quote is unavailable")
            price = row.get("last_price")
            stamp = row.get("timestamp")
            if isinstance(price, bool):
                raise ValueError("Kite quote price is invalid")
            try:
                price = float(price)
                stamp = (
                    stamp
                    if isinstance(stamp, datetime)
                    else datetime.fromisoformat(str(stamp))
                )
                stamp = (
                    stamp.replace(tzinfo=self.MARKET_TZ)
                    if stamp.tzinfo is None
                    else stamp.astimezone(self.MARKET_TZ)
                )
            except (ValueError, TypeError, OverflowError):
                raise ValueError("Kite quote price or timestamp is invalid") from None
            age = (current - stamp).total_seconds()
            if (
                not isfinite(price)
                or price <= 0
                or not -5 <= age <= self.max_age_seconds
            ):
                raise ValueError("Kite quote is stale or invalid")
            output[instrument] = {"last_price": price, "timestamp": stamp.isoformat()}
        return output

    def safe_ltp(self, instruments: list[str]) -> dict:
        return self.prices(instruments)
