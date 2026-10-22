"""NIFTY 50 Kite live watchlist; official constituents remain selectable if quotes fail."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import api_client
from webapp.ui import page_header, render_api_error

page_header(
    "NIFTY 50 Watchlist",
    "All available official NIFTY 50 constituents with live Kite LTP and day changes.",
    kicker="01 / Watchlist",
)


@st.cache_data(ttl=600, show_spinner=False)
def load_constituents() -> dict:
    return api_client(timeout=35).get_json(
        "/workspace/watchlist/NIFTY%2050/constituents", timeout=35
    )


@st.cache_data(ttl=45, show_spinner=False)
def load_live_watchlist() -> dict:
    return api_client(timeout=45).get_json(
        "/workspace/watchlist/NIFTY%2050", timeout=45
    )


if st.button("Refresh NSE constituents & Kite prices"):
    load_constituents.clear()
    load_live_watchlist.clear()
    st.rerun()

try:
    constituents = load_constituents()
except ApiError as exc:
    render_api_error(exc, title="NIFTY 50 membership unavailable")
    st.warning(
        "Official NSE membership is unavailable; no unverified constituent "
        "list or fabricated prices will be substituted."
    )
    st.stop()

members = [
    row for row in constituents.get("rows", [])
    if isinstance(row, dict) and str(row.get("symbol") or "").strip()
]
if not members:
    st.error("NIFTY 50 index contains no validated NSE members.")
    st.stop()

if constituents.get("stale"):
    st.warning(
        str(constituents.get("source_warning") or
            "Showing previously validated, potentially stale NSE constituents.")
    )

quotes = {}
try:
    quotes = load_live_watchlist()
except ApiError:
    st.warning(
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
    rows.append({
        "Symbol": symbol,
        "Company": member.get("stock_name") or symbol,
        "LTP (₹)": quote.get("ltp"),
        "Day Change (₹)": quote.get("day_change_rs"),
        "Day Change (%)": quote.get("day_change_pct"),
    })

quoted = sum(1 for row in rows if row["LTP (₹)"] is not None)
a, b, c = st.columns(3)
a.metric("NIFTY 50 constituents", len(members))
b.metric("Available Kite quotes", f"{quoted}/{len(members)}")
c.metric("Price source", "Kite" if quoted else "Unavailable")

frame = pd.DataFrame(rows)
search = st.text_input(
    "Search stock", placeholder="Company name or NSE symbol",
    key="tf_nifty50_search",
)
if search.strip():
    matches = (
        frame["Symbol"].str.contains(search.strip(), regex=False, case=False, na=False)
        | frame["Company"].str.contains(search.strip(), regex=False, case=False, na=False)
    )
    frame = frame.loc[matches].reset_index(drop=True)

if frame.empty:
    st.info("No constituent matches this search.")
    st.stop()

st.dataframe(
    frame, hide_index=True, use_container_width=True,
    column_config={
        "LTP (₹)": st.column_config.NumberColumn(format="₹%.2f"),
        "Day Change (₹)": st.column_config.NumberColumn(format="₹%.2f"),
        "Day Change (%)": st.column_config.NumberColumn(format="%.2f%%"),
    },
)
symbol_list = frame["Symbol"].tolist()
selected = st.selectbox(
    "Select a NIFTY 50 stock",
    options=symbol_list,
    format_func=lambda symbol: f"{symbol} — {next((r['Company'] for r in rows if r['Symbol'] == symbol), symbol)}",
    key="tf_nifty50_stock_selector",
)
if selected:
    chosen = next((r for r in rows if r["Symbol"] == selected), {})
    left, right, delta = st.columns(3)
    left.metric("Selected NSE stock", selected)
    right.metric(
        "LTP (₹)", f"₹{chosen['LTP (₹)']:,.2f}" if chosen.get("LTP (₹)") is not None else "—"
    )
    delta.metric(
        "Day Change (%)",
        f"{chosen['Day Change (%)']:.2f}%" if chosen.get("Day Change (%)") is not None else "—",
    )
st.caption(
    "NSE official index membership; quotes from Kite Connect. "
    "Day change measures LTP against the previous close. "
    "Data may be stale when the market is closed."
)
