"""Consistent Indian-market timestamp presentation, preserving source evidence."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
TRADE_TIME_FIELDS = frozenset(
    {
        "entry_at",
        "exit_at",
        "entry_signal_at",
        "exit_signal_at",
        "created_at",
        "closed_at",
        "opened_at",
        "first_entry_at",
        "last_exit_at",
        "realized_at",
        "entry_time",
        "exit_time",
        "entry_date",
        "exit_date",
        "order_timestamp",
        "exchange_timestamp",
        "exchange_update_timestamp",
        "fill_timestamp",
    }
)


def market_timestamp(value) -> datetime | None:
    """Naive market/paper times follow the existing Asia/Kolkata contract."""
    if value is None or isinstance(value, (bool, int, float)):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        # ISO input only; do not guess whether 03/04 means March or April.
        if not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])", text):
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    try:
        return parsed.astimezone(IST)
    except (ValueError, OverflowError):
        return None


def display_market_time(value, *, daily: bool = False) -> str:
    if (
        value is None
        or value is pd.NA
        or value is pd.NaT
        or (isinstance(value, float) and math.isnan(value))
        or (isinstance(value, str) and not value.strip())
    ):
        return "—"
    stamp = market_timestamp(value)
    if stamp is None:
        return "Invalid timestamp"
    only_date = isinstance(value, date) and not isinstance(value, datetime)
    only_date = only_date or bool(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value).strip())
    )
    if daily:
        return stamp.strftime("%d %b %Y") + " (daily bar, IST)"
    if only_date:
        return stamp.strftime("%d %b %Y") + " (time unavailable)"
    return stamp.strftime("%d %b %Y, %H:%M:%S IST")


def format_trade_frame(frame: pd.DataFrame, *, daily: bool = False) -> pd.DataFrame:
    result = frame.copy()
    for field in TRADE_TIME_FIELDS.intersection(result.columns):
        result[field] = result[field].map(
            lambda value: display_market_time(value, daily=daily)
        )
    return result


def export_trade_frame(frame: pd.DataFrame, *, daily: bool = False) -> pd.DataFrame:
    """Keep raw timestamps and add explicit, human-readable IST columns."""
    result = frame.copy()
    for field in sorted(TRADE_TIME_FIELDS.intersection(result.columns)):
        # Idempotent when a caller already prepared this export.
        column = field + "_ist"
        if column not in result:
            result[column] = result[field].map(
                lambda value: display_market_time(value, daily=daily)
            )
    return result
