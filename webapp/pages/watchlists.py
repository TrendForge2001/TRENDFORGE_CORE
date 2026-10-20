"""NIFTY 100 watchlist: constituents first, live quotes optional."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import page_header, render_api_error


page_header(
    "NIFTY 100 Watchlist",
    "Select any official NIFTY 100 constituent. Kite quotes appear when available; missing live data never hides stock names.",
    kicker="Watchlist",
)
client = api_client(timeout=30)


@st.cache_data(ttl=600, show_spinner=False)
def load_constituents() -> dict:
    return api_client(timeout=25).get_json(
        "/workspace/watchlist/NIFTY%20100/constituents", timeout=25
    )


@st.cache_data(ttl=75, show_spinner=False)
def load_live_watchlist() -> dict:
    return api_client(timeout=35).get_json(
        "/workspace/watchlist/NIFTY%20100", timeout=35
    )


with st.sidebar:
    pass

heading_left, heading_right = st.columns([3, 1])
with heading_right:
    if st.button("Refresh watchlist", use_container_width=True):
        load_constituents.clear()
        load_live_watchlist.clear()
        st.rerun()

try:
    constituents = load_constituents()
except ApiError as exc:
    render_api_error(exc, title="NSE NIFTY 100 constituents unavailable")
    st.info(
        "The constituent list is sourced from official NSE index data, not from a scanner. "
        "Please retry Refresh watchlist when the provider connection recovers."
    )
    st.stop()

members = [
    row for row in constituents.get("rows", [])
    if isinstance(row, dict) and str(row.get("symbol") or "").strip()
]
if not members:
    st.error("NSE returned no validated NIFTY 100 constituents; no symbols were invented.")
    st.stop()

if constituents.get("stale"):
    st.warning(
        "Showing the last validated NSE member list because the official source "
        "could not be refreshed. Constituent changes may not be reflected yet."
    )

quotes = {}
quote_issue = None
try:
    quotes = load_live_watchlist()
except ApiError as exc:
    quote_issue = str(exc)

prices_by_symbol = {
    str(row.get("symbol") or "").upper(): row
    for row in quotes.get("rows", [])
    if isinstance(row, dict)
}
rows = []
for member in members:
    symbol = str(member["symbol"]).upper()
    quote = prices_by_symbol.get(symbol, {})
    rows.append(
        {
            "Stock name": member.get("stock_name") or symbol,
            "Symbol": symbol,
            "Day change (₹)": quote.get("day_change_rs"),
            "Day change (%)": quote.get("day_change_pct"),
            "Latest trading price (₹)": quote.get("ltp"),
            "Sector": member.get("sector"),
        }
    )

quoted_count = sum(
    1 for row in rows
    if row.get("Latest trading price (₹)") is not None
)
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("NIFTY 100 constituents", len(rows))
with col2:
    st.metric("Live prices available", f"{quoted_count}/{len(rows)}")
with col3:
    st.metric("Quote source", "Kite" if quoted_count else "Unavailable")

if constituents.get("fetched_at"):
    st.caption(
        f"NSE constituent snapshot: {constituents['fetched_at']} "
        f"· Source: {constituents.get('source', 'official NSE')}"
    )

if quote_issue or quotes.get("quote_error"):
    st.warning(
        "Kite live quotes are currently unavailable. The stock selector remains "
        "usable; prices and daily changes are shown as missing rather than zero."
    )
    with st.expander("Quote provider details"):
        st.code(str(quote_issue or quotes["quote_error"])[:800])
elif quoted_count < len(rows):
    st.info(
        "Some live quotes are unavailable. Empty price/change cells mean "
        "no verified Kite quote was returned."
    )

frame = pd.DataFrame(rows)
symbols = [row["Symbol"] for row in rows]
names = {row["Symbol"]: row["Stock name"] for row in rows}

selected = str(st.session_state.get("tf_selected_watch_symbol") or "").upper()
if selected not in names:
    selected = ""
selected = st.selectbox(
    "Select a NIFTY 100 stock",
    options=symbols,
    index=symbols.index(selected) if selected else None,
    format_func=lambda key: f"{names.get(key, key)} · {key}",
    placeholder="Search stock name or NSE symbol",
    key="tf_nifty100_stock_selector",
)
if selected:
    st.session_state["tf_selected_watch_symbol"] = selected
    st.session_state["tf_selected_watch_name"] = names.get(selected, selected)

st.caption("Click any row or choose a stock from the dropdown to view its chart and intelligence.")
event = st.dataframe(
    frame,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="nifty100_live_table",
    column_config={
        "Day change (₹)": st.column_config.NumberColumn(
            "Day change (₹)", format="₹%.2f"
        ),
        "Day change (%)": st.column_config.NumberColumn(
            "Day change (%)", format="%.2f%%"
        ),
        "Latest trading price (₹)": st.column_config.NumberColumn(
            "Latest trading price (₹)", format="₹%.2f"
        ),
    },
)
selected_rows = list(getattr(event.selection, "rows", []) or [])
if selected_rows:
    chosen = symbols[selected_rows[0]]
    if chosen != st.session_state.get("tf_selected_watch_symbol"):
        st.session_state["tf_selected_watch_symbol"] = chosen
        st.session_state["tf_selected_watch_name"] = names[chosen]
        st.rerun()

symbol = str(st.session_state.get("tf_selected_watch_symbol") or "").upper()
if not symbol or symbol not in names:
    st.info("Choose a stock above to open chart, OHLC, news and corporate actions.")
    st.stop()

st.divider()
st.subheader(f"{names[symbol]} · {symbol}")
left, right = st.columns([4, 1])
with left:
    st.caption("Kite daily candles / OHLC · persisted TrendForge news and corporate actions")
with right:
    refresh_intelligence = st.button(
        "Refresh intelligence", use_container_width=True
    )
if refresh_intelligence:
    if not admin_key_configured():
        st.error("Admin API Key is required to refresh intelligence.")
    else:
        try:
            client.post_json(
                "/intelligence/refresh",
                {"symbols": [symbol], "domains": ["news", "corporate_actions"], "days": 180},
                timeout=120,
            )
            st.success("Intelligence refreshed.")
            st.rerun()
        except ApiError as exc:
            render_api_error(exc, title="Intelligence refresh failed")

try:
    detail = client.get_json(
        f"/workspace/stock/{symbol}", params={"period": "6mo"}, timeout=70
    )
except ApiError as exc:
    render_api_error(exc, title=f"{symbol} stock detail unavailable")
    st.info(
        "The stock remains selectable. Chart/OHLC require Kite access; "
        "if its daily token expired, refresh it in Render."
    )
    st.stop()

ohlc = detail.get("ohlc") if isinstance(detail.get("ohlc"), dict) else {}
def money(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        return "—"
    return f"₹{number:,.2f}" if number > 0 else "—"

q1, q2, q3, q4, q5 = st.columns(5)
for col, label, val in [
    (q1, "LTP", detail.get("ltp")),
    (q2, "Open", ohlc.get("open")),
    (q3, "High", ohlc.get("high")),
    (q4, "Low", ohlc.get("low")),
    (q5, "Prev close", ohlc.get("previous_close")),
]:
    with col:
        st.metric(label, money(val))

candles = detail.get("candles")
candles = candles if isinstance(candles, list) else []
if candles:
    chart_frame = pd.DataFrame(candles)
    chart_frame["date"] = pd.to_datetime(chart_frame["date"], errors="coerce")
    chart_frame = chart_frame.dropna(subset=["date"])
    base = alt.Chart(chart_frame).encode(x=alt.X("date:T", title=None))
    wick = base.mark_rule().encode(
        y=alt.Y("low:Q", title="Price (₹)"), y2="high:Q"
    )
    body = base.mark_bar(size=5).encode(
        y="open:Q", y2="close:Q",
        tooltip=[
            alt.Tooltip("date:T", title="Date"),
            alt.Tooltip("open:Q", format=".2f"),
            alt.Tooltip("high:Q", format=".2f"),
            alt.Tooltip("low:Q", format=".2f"),
            alt.Tooltip("close:Q", format=".2f"),
            alt.Tooltip("volume:Q", format=","),
        ],
    )
    st.altair_chart((wick + body).properties(height=390), use_container_width=True)
else:
    st.info("No historical candles were returned for the selected stock.")

news = detail.get("news") if isinstance(detail.get("news"), dict) else {}
actions = (
    detail.get("corporate_actions")
    if isinstance(detail.get("corporate_actions"), dict)
    else {}
)
tab_news, tab_actions = st.tabs(["News", "Corporate actions"])
for tab, events, preferred, absent in [
    (tab_news, news.get("events"), ["event_at", "headline", "sentiment_label", "source"],
     "No persisted news for this stock."),
    (tab_actions, actions.get("events"), ["event_at", "event_type", "headline", "source"],
     "No persisted corporate actions for this stock."),
]:
    with tab:
        if isinstance(events, list) and events:
            table = pd.DataFrame(events)
            st.dataframe(
                table[[c for c in preferred if c in table.columns]],
                use_container_width=True, hide_index=True,
            )
        else:
            st.info(absent + " Refresh intelligence when available.")
