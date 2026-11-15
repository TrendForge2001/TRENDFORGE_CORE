"""Shared index/sector/F&O watchlists with source-labelled membership."""

from __future__ import annotations

from urllib.parse import quote as url_quote

import pandas as pd
import streamlit as st

from config.stock_lists import resolve_stock_list
from webapp.api_client import ApiError, TrendForgeApi
from webapp.institutional_selector import filter_symbols
from webapp.market_colours import market_frame
from webapp.runtime import admin_key, api_url
from webapp.stock_lists import ROOT_MANAGED, selected_stock_list, stock_list_picker
from webapp.ui import page_header, render_api_error
from webapp.workspace_layout import workspace_panels

page_header(
    "Stock Watchlists",
    "Choose an index, sector or F&O stock list. "
    "Equity prices and daily changes use Kite NSE quotes.",
    kicker="01 / Watchlist",
)


@st.cache_data(ttl=600, show_spinner=False)
def load_constituents(backend_url: str, index_name="NIFTY 50") -> dict:
    return TrendForgeApi(
        backend_url, admin_key=admin_key(), default_timeout=35
    ).get_json(
        f"/workspace/watchlist/{url_quote(index_name, safe='')}/constituents",
        timeout=35,
    )


@st.cache_data(ttl=45, show_spinner=False)
def load_live_watchlist(backend_url: str, index_name="NIFTY 50") -> dict:
    return TrendForgeApi(
        backend_url, admin_key=admin_key(), default_timeout=45
    ).get_json(f"/workspace/watchlist/{url_quote(index_name, safe='')}", timeout=45)


controls, results_panel = workspace_panels("watchlist")
with controls:
    index_name = (
        selected_stock_list()
        if st.session_state.get(ROOT_MANAGED)
        else stock_list_picker(key="tf_watchlist_list")
    )

if controls.button("Refresh constituents & Kite prices"):
    load_constituents.clear()
    load_live_watchlist.clear()
    st.rerun()

try:
    constituents = load_constituents(api_url(), index_name)
except ApiError as exc:
    render_api_error(exc, title=index_name + " membership unavailable")
    controls.warning(
        "Membership is unavailable. Refresh the selected list to try again."
    )
    st.stop()

members = [
    row
    for row in constituents.get("rows", [])
    if isinstance(row, dict) and str(row.get("symbol") or "").strip()
]
if not members:
    st.error("The selected stock list contains no validated members.")
    st.stop()

try:
    allowed_symbols = set(
        filter_symbols(
            TrendForgeApi(api_url(), admin_key=admin_key()),
            [r["symbol"] for r in members],
        )
    )
    members = [r for r in members if r["symbol"] in allowed_symbols]
except ApiError as exc:
    render_api_error(exc, title="Institutional selector unavailable")
    st.stop()
if not members:
    st.info("No stocks in this list match the selected Big Shark signal.")
    st.stop()

if resolve_stock_list(index_name)[1].kind == "index":
    with results_panel:
        st.caption(
            "Index references for browsing; choose a constituent stock list "
            "for equity research."
        )
        st.dataframe(
            pd.DataFrame(members)[["stock_name", "symbol", "sector"]].rename(
                columns={
                    "stock_name": "Index",
                    "symbol": "Reference symbol",
                    "sector": "Market",
                }
            ),
            hide_index=True,
            width="stretch",
        )
    st.stop()

if constituents.get("stale"):
    controls.warning(
        str(
            constituents.get("source_warning")
            or "Showing previously validated, potentially stale NSE constituents."
        )
    )

quotes = {}
try:
    quotes = load_live_watchlist(api_url(), index_name)
except ApiError:
    controls.warning(
        "Kite quote retrieval is unavailable. NSE constituents remain visible; "
        "unavailable LTP/change values are blank, never zero."
    )
if quotes.get("quote_error"):
    st.warning("Kite returned partial or unavailable market quotes.")

prices = {
    str(item.get("symbol") or "").upper(): item
    for item in quotes.get("rows", [])
    if isinstance(item, dict)
}
rows = []
for member in members:
    symbol = str(member.get("symbol") or "").upper()
    quote = prices.get(symbol, {})
    rows.append(
        {
            "Symbol": symbol,
            "Company": member.get("stock_name") or symbol,
            "Sector": member.get("sector") or "Unclassified",
            "Scanner score": next(
                (
                    row.get("score")
                    for row in st.session_state.get("tf_r726_scan_result", {}).get(
                        "results", []
                    )
                    if row.get("symbol") == symbol and row.get("signal") != "ERROR"
                ),
                None,
            ),
            "LTP (₹)": quote.get("ltp"),
            "Day Change (₹)": quote.get("day_change_rs"),
            "Day Change (%)": quote.get("day_change_pct"),
        }
    )

quoted = sum(1 for row in rows if row["LTP (₹)"] is not None)
with controls:
    a, b = st.columns(2)
    a.metric("List constituents", len(members))
    b.metric("Available Kite quotes", f"{quoted}/{len(members)}")
    st.caption("Price source: " + ("Kite" if quoted else "Unavailable"))

    st.caption(
        "Stock scores use the latest scan in this session; "
        "blank means not scored or unavailable."
    )
    frame = pd.DataFrame(rows)
    if resolve_stock_list(index_name)[1].grouped:
        frame = frame.sort_values(["Sector", "Company"]).reset_index(drop=True)
    search = st.text_input(
        "Search stock",
        placeholder="Company name or NSE symbol",
        key="tf_nifty50_search",
    )
    if search.strip():
        matches = frame["Symbol"].str.contains(
            search.strip(), regex=False, case=False, na=False
        ) | frame["Company"].str.contains(
            search.strip(), regex=False, case=False, na=False
        )
        frame = frame.loc[matches].reset_index(drop=True)

    if frame.empty:
        st.info("No constituent matches this search.")
        st.stop()

with results_panel:
    st.dataframe(
        market_frame(frame),
        hide_index=True,
        width="stretch",
        column_config={
            "LTP (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Day Change (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Day Change (%)": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )
with controls:
    st.caption(
        "Membership source: " + str(constituents.get("source") or "Unavailable") + ". "
        "Prices: NSE listings through Kite Connect. "
        "Day change measures LTP against the previous close. "
        "Snapshots refresh on page interaction rather than streaming ticks. "
        "Cached quotes may be stale, including during market hours."
    )
    if constituents.get("source_warning") and not constituents.get("stale"):
        st.caption(constituents["source_warning"])
