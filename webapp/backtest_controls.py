"""Two-choice historical backtest setup with explicit fixed model settings."""

from __future__ import annotations

import re
import time
from urllib.parse import quote

import streamlit as st

from config.nifty_universes import NIFTY_UNIVERSES
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from scanner.multi_strategy_engine import REVIEW_REQUIRED
from scanner.strategy_registry import list_scanner_choices
from scanner.technical_strategy import strategy_profile
from webapp.api_client import ApiError


def backtest_choices() -> dict[str, dict]:
    choices = {}
    for mode in ("swing", "intraday", "positional"):
        for row in list_scanner_choices(mode=mode):
            if row["strategy_id"] in REVIEW_REQUIRED:
                continue
            setup = EMA_PIVOT_SETUPS.get(row["strategy_id"])
            borrow = setup is not None and setup.direction == -1
            label = f"{mode.title()} · {row['name']}"
            if borrow:
                label += " · borrow assumed"
            profile = strategy_profile(mode)
            choices[label] = {
                "strategy_id": row["strategy_id"],
                "mode": mode,
                "period": profile.default_period,
                "interval": row["default_interval"],
                "short_borrow_available": borrow,
            }
    return choices


def stock_list(client, index: str) -> dict:
    """Load the entire selected official index, including named sector indices."""
    if index not in NIFTY_UNIVERSES:
        raise ApiError("Choose an official stock list")
    cache = st.session_state.setdefault("tf_backtest_stock_lists", {})
    key = (getattr(client, "base_url", ""), index)
    cached = cache.get(key)
    if cached is None or time.monotonic() - cached[0] > 600:
        payload = client.get_json(
            f"/workspace/watchlist/{quote(index, safe='')}/constituents", timeout=35
        )
        rows = payload.get("rows")
        if (
            not isinstance(rows, list)
            or not rows
            or any(
                not isinstance(row, dict)
                or not isinstance(row.get("symbol"), str)
                or not re.fullmatch(r"[A-Z0-9][A-Z0-9._&-]{0,29}", row["symbol"])
                or ".." in row["symbol"]
                for row in rows
            )
        ):
            raise ApiError("Official NSE stock-list membership is unavailable")
        cache[key] = (time.monotonic(), payload)
    payload = cache[key][1]
    return {
        "symbols": list(dict.fromkeys(row["symbol"] for row in payload["rows"])),
        "index": index,
        "sector": "All sectors",
        "source": payload.get("source"),
        "fetched_at": payload.get("fetched_at"),
        "stale": bool(payload.get("stale")),
    }
