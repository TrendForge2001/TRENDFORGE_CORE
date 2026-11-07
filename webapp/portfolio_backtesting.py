"""Two choices, two actions and one historical entry/exit report."""

from __future__ import annotations

from uuid import uuid4

import pandas as pd
import streamlit as st

from config.nifty_universes import NIFTY_UNIVERSES
from config.scanner_capacity import MAX_BACKTEST_SYMBOLS
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from scanner.portfolio_policy import number
from webapp.api_client import ApiError
from webapp.backtest_controls import backtest_choices, stock_list
from webapp.backtest_trade_report import TRADE_COLUMNS, trade_report, validate_result
from webapp.market_colours import market_frame
from webapp.nifty_selection import scan_nifty_stocks
from webapp.ui import render_api_error

RESULT_KEY = "tf_r726_backtest_result"
SCAN_KEY = "tf_compact_backtest_scan"
SCOPE_KEY = "tf_compact_backtest_scope"
__all__ = ["render_portfolio_backtesting", "render_result", "validate_result"]


def render_result(result: dict, *, controls=None) -> None:
    """Only actual exits are rendered; partial exits keep their entry reference."""
    ledger = trade_report(result)
    st.subheader("Trade entries and exits")
    if ledger.empty:
        st.info("No historical trades passed this strategy's entry rules.")
        return
    st.caption(
        "One row per exit fill. Partial and final exits share a trade number. "
        "Use the table download icon to export this trade report."
    )
    display = ledger.copy()
    for field in ("entry_at", "exit_at"):
        display[field] = pd.to_datetime(display[field], utc=True).dt.tz_convert(
            "Asia/Kolkata"
        )
    date_format = (
        "DD MMM YYYY" if result.get("interval") == "1d" else "DD MMM YYYY HH:mm"
    )
    st.dataframe(
        market_frame(display),
        hide_index=True,
        width="stretch",
        column_order=TRADE_COLUMNS,
        column_config={
            "trade_number": st.column_config.NumberColumn("Trade", format="%d"),
            "symbol": st.column_config.TextColumn("Stock"),
            "side": st.column_config.TextColumn("Side"),
            "entry_at": st.column_config.DatetimeColumn(
                "Entry (IST)", format=date_format, timezone="Asia/Kolkata"
            ),
            "entry_price": st.column_config.NumberColumn("Entry price", format="₹%.2f"),
            "entry_quantity": st.column_config.NumberColumn("Entry qty", format="%d"),
            "exit_at": st.column_config.DatetimeColumn(
                "Exit (IST)", format=date_format, timezone="Asia/Kolkata"
            ),
            "exit_price": st.column_config.NumberColumn("Exit price", format="₹%.2f"),
            "quantity": st.column_config.NumberColumn("Exit qty", format="%d"),
            "exit_reason": st.column_config.TextColumn("Exit reason"),
            "transaction_costs": st.column_config.NumberColumn("Costs", format="₹%.2f"),
            "net_pnl": st.column_config.NumberColumn("Net P&L", format="₹%.2f"),
        },
    )
    if result.get("interval") == "1d":
        st.caption(
            "Daily-bar entries/exits identify the candle date; "
            "exact intrabar times are unavailable."
        )
    excluded = (result.get("history_alignment") or {}).get("excluded_symbols", [])
    if excluded:
        st.caption(
            f"{len(excluded)} stocks were excluded for incomplete "
            "or misaligned history."
        )


def current_candidates(snapshot: dict) -> list[dict]:
    candidates = []
    for row in snapshot.get("results", []):
        if row.get("signal") not in {"BUY", "SELL"}:
            continue
        research = snapshot.get("strategy_id") in EMA_PIVOT_SETUPS
        if (research and row.get("entry_state") != "ARMED") or (
            not research and row.get("execution_eligible") is not True
        ):
            continue
        entry, stop = number(row.get("entry")), number(row.get("stoploss"))
        if entry is None or stop is None or min(entry, stop) <= 0:
            continue
        if (row["signal"] == "BUY" and stop >= entry) or (
            row["signal"] == "SELL" and stop <= entry
        ):
            continue
        candidates.append(row)
    return sorted(
        candidates, key=lambda row: (-(number(row.get("score")) or 0), row["symbol"])
    )


def render_portfolio_backtesting(client, *, authorized: bool) -> None:
    choices = backtest_choices()
    strategy_column, stocks_column = st.columns([3, 2])
    label = strategy_column.selectbox(
        "Scanner strategy", list(choices), key="compact_backtest_strategy"
    )
    index = stocks_column.selectbox(
        "Stock list", list(NIFTY_UNIVERSES), key="compact_backtest_list"
    )
    settings = choices[label]
    selection = {"symbols": [], "index": index}
    try:
        selection = stock_list(client, index)
    except ApiError as exc:
        render_api_error(exc, title="Stock list unavailable")
    signature = (
        settings["strategy_id"],
        settings["mode"],
        settings["period"],
        index,
        tuple(selection["symbols"]),
    )
    if st.session_state.get(SCOPE_KEY) != signature:
        st.session_state.pop(RESULT_KEY, None)
        st.session_state.pop(SCAN_KEY, None)
        st.session_state[SCOPE_KEY] = signature
    st.caption(
        f"{len(selection['symbols'])} stocks · {settings['mode'].title()} · "
        f"{settings['period']} history · ₹1,00,000 capital · ₹0 reserve · "
        "up to 3 positions"
    )
    st.caption(
        "Costs: 12 bps per side; slippage: 5 bps. Strategy risk limits and whole-share "
        "rounding can leave cash uninvested. Current index membership is used."
    )
    if settings["short_borrow_available"]:
        st.caption(
            "This selected historical short simulation assumes borrow "
            "availability; no broker orders."
        )
    if selection.get("stale"):
        st.warning(
            "The last validated stock list is being used; "
            "current membership could not be refreshed."
        )
    allowed = authorized and 0 < len(selection["symbols"]) <= MAX_BACKTEST_SYMBOLS
    scan_column, backtest_column = st.columns(2)
    scan = scan_column.button("Scan stocks", disabled=not allowed, width="stretch")
    run = backtest_column.button(
        "Backtest", type="primary", disabled=not allowed, width="stretch"
    )
    if not authorized:
        st.info("An Admin API Key is required to scan or backtest.")
    if len(selection["symbols"]) > MAX_BACKTEST_SYMBOLS:
        st.error(f"Choose a stock list with at most {MAX_BACKTEST_SYMBOLS} members.")
    if scan:
        st.session_state.pop(SCAN_KEY, None)
        try:
            with st.spinner("Scanning the selected stock list…"):
                snapshot = scan_nifty_stocks(
                    client,
                    selection,
                    mode=settings["mode"],
                    period=settings["period"],
                    strategy_id=settings["strategy_id"],
                )
            st.session_state[SCAN_KEY] = snapshot
        except ApiError as exc:
            render_api_error(exc, title="Scanner unavailable")
    snapshot = st.session_state.get(SCAN_KEY)
    if snapshot:
        candidates = current_candidates(snapshot)
        names = ", ".join(
            f"{row['symbol']} ({row['signal']})" for row in candidates[:3]
        )
        st.caption(
            f"Scan: {len(candidates)} current entry setups; "
            f"{snapshot['error_symbols']} data errors. "
            + (
                "Top candidates: " + names + "."
                if names
                else "No current entry setups."
            )
        )
        if candidates and settings["strategy_id"] in EMA_PIVOT_SETUPS:
            st.caption("Armed setups still require a next-candle trigger.")
    if run:
        st.session_state.pop(RESULT_KEY, None)
        try:
            with st.spinner(
                "Backtesting historical signals across the selected stock list…"
            ):
                result = client.post_json(
                    "/technical/portfolio-backtest",
                    {
                        "symbols": selection["symbols"],
                        "mode": settings["mode"],
                        "strategy_id": settings["strategy_id"],
                        "period": settings["period"],
                        "cost_bps": 12.0,
                        "slippage_bps": 5.0,
                        "short_borrow_available": settings["short_borrow_available"],
                        "run_id": "portfolio-ui-" + uuid4().hex,
                    },
                    timeout=600,
                )
            validate_result(result)
            if (
                result.get("strategy_id") != settings["strategy_id"]
                or result.get("mode") != settings["mode"]
            ):
                raise ApiError(
                    "The returned backtest does not match the selected strategy"
                )
            st.session_state[RESULT_KEY] = result
        except ApiError as exc:
            render_api_error(exc, title="Historical backtest failed")
    result = st.session_state.get(RESULT_KEY)
    if result is not None:
        try:
            render_result(result)
        except ApiError as exc:
            st.session_state.pop(RESULT_KEY, None)
            render_api_error(exc, title="Historical report unavailable")
    else:
        st.caption(
            "Backtest evaluates historical entries across the full selected "
            "list, independently of today's scan."
        )
