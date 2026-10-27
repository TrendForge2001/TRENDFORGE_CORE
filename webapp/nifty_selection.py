"""Index/sector stock selection through the backend's official NSE boundary."""

from __future__ import annotations

import time
from urllib.parse import quote
from uuid import uuid4

import streamlit as st

from config.nifty_universes import NIFTY_UNIVERSES
from webapp.api_client import ApiError
from webapp.ui import render_api_error

GROUPED = "NIFTY LARGEMIDCAP 250 (Grouped by sector)"


def select_nifty_stocks(client, *, key: str, single: bool = False) -> dict:
    index = st.selectbox(
        "Nifty index / sector list", [*NIFTY_UNIVERSES, GROUPED], key=key + "_index"
    )
    base = "NIFTY LARGEMIDCAP 250" if index == GROUPED else index
    cache = st.session_state.setdefault("tf_nifty_universes", {})
    cache_key = (getattr(client, "base_url", ""), base)
    if st.button("Refresh stock list", key=key + "_refresh"):
        cache.pop(cache_key, None)
    cached = cache.get(cache_key)
    if cached is None or time.monotonic() - cached[0] > 600:
        try:
            payload = client.get_json(
                f"/workspace/watchlist/{quote(base, safe='')}/constituents",
                timeout=35,
            )
            rows = payload.get("rows")
            if (
                not isinstance(rows, list)
                or not rows
                or not all(isinstance(row, dict) and row.get("symbol") for row in rows)
            ):
                raise ApiError("Official NSE membership is unavailable")
            cache[cache_key] = (time.monotonic(), payload)
        except ApiError as exc:
            render_api_error(exc, title="Nifty constituent list unavailable")
            return {"symbols": [], "index": base, "sector": "All sectors"}
    payload = cache[cache_key][1]
    if payload.get("stale"):
        st.warning(
            payload.get("source_warning")
            or "Using the last validated NSE constituent list."
        )
    members = payload["rows"]
    sectors = sorted({row.get("sector") or "Unclassified" for row in members})
    sector = st.selectbox(
        "Sector / industry", ["All sectors", *sectors], key=key + "_sector"
    )
    members = [
        row
        for row in members
        if sector == "All sectors" or (row.get("sector") or "Unclassified") == sector
    ]
    symbols = list(dict.fromkeys(row["symbol"] for row in members))
    if single:
        selected = st.selectbox("NSE stock", symbols, key=key + "_stock")
        symbols = [selected] if selected else []
    elif st.checkbox("Choose individual stocks", key=key + "_custom"):
        symbols = st.multiselect(
            "Stocks in selected list", symbols, default=symbols, key=key + "_stocks"
        )
    st.caption(f"{base} · {sector} · {len(symbols)} selected stocks")
    return {
        "symbols": symbols,
        "index": base,
        "sector": sector,
        "source": payload.get("source"),
        "fetched_at": payload.get("fetched_at"),
        "stale": bool(payload.get("stale")),
    }


def scan_nifty_stocks(
    client,
    selection: dict,
    *,
    mode: str,
    period: str,
    strategy_id: str | None,
    top_n: int = 100,
) -> dict:
    """Respect the API's 100-symbol cap without truncating larger NSE lists."""
    symbols = list(dict.fromkeys(selection["symbols"]))
    if not symbols:
        raise ApiError("Select a nonempty Nifty list")
    run_id = "nifty-scan-" + uuid4().hex
    rows = []
    runs = []
    successful_chunks = 0
    for offset in range(0, len(symbols), 100):
        chunk = symbols[offset : offset + 100]
        try:
            result = client.post_json(
                "/technical/scan",
                {
                    "symbols": chunk,
                    "mode": mode,
                    "period": period,
                    "strategy_id": strategy_id,
                    "top_n": 100,
                    "execute_paper": False,
                    "run_id": f"{run_id}-{offset // 100}",
                },
                timeout=240,
            )
            chunk_rows = result.get("results")
            if (
                result.get("status") != "completed"
                or result.get("mode") != mode
                or result.get("strategy_id") != strategy_id
                or not isinstance(chunk_rows, list)
                or not all(isinstance(row, dict) for row in chunk_rows)
                or sorted(row.get("symbol", "") for row in chunk_rows) != sorted(chunk)
            ):
                raise ApiError("Invalid scanner result")
            successful_chunks += 1
            rows.extend(
                {**row, "score": None} if row.get("signal") == "ERROR" else row
                for row in chunk_rows
            )
            runs.append(result.get("run_id"))
        except ApiError as exc:
            if exc.status_code in {401, 403}:
                raise
            rows.extend(
                {
                    "symbol": symbol,
                    "signal": "ERROR",
                    "score": None,
                    "error": "Scanner data unavailable",
                }
                for symbol in chunk
            )
    if not successful_chunks:
        raise ApiError("Nifty scanner data is unavailable for the selected stocks")
    valid = [row for row in rows if row.get("signal") != "ERROR"]
    buys = sorted(
        [row for row in valid if row.get("execution_eligible")],
        key=lambda row: float(row.get("score") or 0),
        reverse=True,
    )[:top_n]
    return {
        "status": "completed",
        "run_id": run_id,
        "batch_run_ids": runs,
        "mode": mode,
        "period": period,
        "strategy_id": strategy_id,
        "universe": {k: v for k, v in selection.items() if k != "symbols"},
        "requested_symbols": len(symbols),
        "completed_symbols": len(valid),
        "error_symbols": len(rows) - len(valid),
        "buy_candidates": sum(row.get("signal") == "BUY" for row in buys),
        "sell_candidates": sum(row.get("signal") == "SELL" for row in buys),
        "entry_candidates": len(buys),
        "results": rows,
        "top_picks": buys,
    }
