"""NIFTY 50 live watchlist; missing Kite quotes are never represented as zero."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import api_client
from webapp.ui import page_header, render_api_error

INDEX_URL = "/workspace/watchlist/NIFTY%2050"

page_header(
    "NIFTY 50 Watchlist",
    "Latest Kite market quotes with price and day movement. NSE supplies the index constituents.",
    kicker="01 / Watchlist",
)

@st.cache_data(ttl=45, show_spinner=False)
def fetch_watchlist() -> dict:
    return api_client(timeout=45).get_json(INDEX_URL, timeout=45)

if st.button("Refresh prices", use_container_width=False):
    fetch_watchlist.clear()

try:
    response = fetch_watchlist()
except ApiError as exc:
    render_api_error(exc, title="NIFTY 50 watchlist unavailable")
    st.warning("Live NSE constituent retrieval or Kite quotes could not be completed. No substitute securities or fabricated prices are shown.")
    st.stop()

rows = [r for r in response.get("rows", []) if isinstance(r, dict)]
prices = sum(1 for r in rows if r.get("ltp") is not None)
c1, c2, c3 = st.columns(3)
c1.metric("Constituents", len(rows))
c2.metric("Kite quotes received", f"{prices}/{len(rows)}")
c3.metric("Quote status", str(response.get("quote_status") or "unknown").upper())
if response.get("source_warning"):
    st.warning(str(response["source_warning"]))
if response.get("quote_error"):
    st.warning("Kite live prices are unavailable for some or all stocks. Blank fields are intentional.")
if not rows:
    st.info("NIFTY 50 constituents are not available. Retry the official NSE source.")
    st.stop()

frame = pd.DataFrame([
    {
        "Symbol": r.get("symbol"),
        "Company": r.get("stock_name"),
        "LTP (₹)": r.get("ltp"),
        "Day Change (₹)": r.get("day_change_rs"),
        "Day Change (%)": r.get("day_change_pct"),
    }
    for r in rows
])
search = st.text_input("Find NIFTY 50 stock", placeholder="Search name or symbol")
if search.strip():
    mask = (
        frame["Symbol"].fillna("").str.contains(search.strip(), case=False, regex=False)
        | frame["Company"].fillna("").str.contains(search.strip(), case=False, regex=False)
    )
    frame = frame.loc[mask]
st.dataframe(
    frame,
    use_container_width=True,
    hide_index=True,
    column_config={
        "LTP (₹)": st.column_config.NumberColumn(format="₹%.2f"),
        "Day Change (₹)": st.column_config.NumberColumn(format="₹%.2f"),
        "Day Change (%)": st.column_config.NumberColumn(format="%.2f%%"),
    },
)
st.caption("Source: NSE official NIFTY 50 membership and Kite Connect quotes. Price movement is measured against the preceding close; quotes may be stale outside trading hours.")
