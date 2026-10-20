"""NIFTY 100 live watchlist with integrated stock detail."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "NIFTY 100 Watchlist",
    "Live Kite quotes with day change, latest price, and one-click stock chart, OHLC, news and corporate actions.",
    kicker="Watchlist",
)

client = api_client(timeout=90)

try:
    payload = client.get_json(
        "/workspace/watchlist/NIFTY%20100",
        timeout=90,
    )
except ApiError as exc:
    render_api_error(exc, title="NIFTY 100 watchlist unavailable")
    st.stop()

rows = payload.get("rows")
rows = rows if isinstance(rows, list) else []

m1, m2, m3 = st.columns(3)
with m1:
    st.metric("Index", str(payload.get("index") or "NIFTY 100"))
with m2:
    st.metric("Stocks", int(payload.get("count") or len(rows)))
with m3:
    st.metric("Price source", "KITE")

if payload.get("fetched_at"):
    st.caption(f"Constituent snapshot: {payload.get('fetched_at')}")

if not rows:
    st.warning("No NIFTY 100 quote rows are available.")
    st.stop()

frame = pd.DataFrame(rows).rename(
    columns={
        "stock_name": "Stock name",
        "symbol": "Symbol",
        "day_change_rs": "Day change (₹)",
        "day_change_pct": "Day change (%)",
        "ltp": "Latest trading price (₹)",
        "sector": "Sector",
    }
)
columns = [
    "Stock name",
    "Symbol",
    "Day change (₹)",
    "Day change (%)",
    "Latest trading price (₹)",
    "Sector",
]
frame = frame[[column for column in columns if column in frame.columns]]

info_note("Select a stock row to open the combined market-detail panel below.")
event = st.dataframe(
    frame,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="nifty100_live_table",
)

selected_rows = list(getattr(event.selection, "rows", []) or [])
if selected_rows:
    selected_index = selected_rows[0]
    selected_symbol = str(frame.iloc[selected_index]["Symbol"])
    selected_name = str(frame.iloc[selected_index]["Stock name"])
    st.session_state["tf_selected_watch_symbol"] = selected_symbol
    st.session_state["tf_selected_watch_name"] = selected_name

symbol = str(st.session_state.get("tf_selected_watch_symbol") or "").strip().upper()
name = str(st.session_state.get("tf_selected_watch_name") or symbol).strip()

if not symbol:
    st.info("Select a row in the NIFTY 100 table to view stock details.")
    st.stop()

st.divider()
st.subheader(f"{name} · {symbol}")

detail_top, refresh_col = st.columns([4, 1])
with detail_top:
    st.caption(
        "Kite daily candles and live quote. News/corporate actions use TrendForge persisted intelligence."
    )
with refresh_col:
    refresh_intelligence = st.button(
        "Refresh intelligence",
        use_container_width=True,
    )

if refresh_intelligence:
    if not admin_key_configured():
        st.error("Enter the Admin API Key to refresh news/corporate actions.")
    else:
        try:
            client.post_json(
                "/intelligence/refresh",
                {
                    "symbols": [symbol],
                    "domains": ["news", "corporate_actions"],
                    "days": 180,
                },
                timeout=120,
            )
            st.success("Intelligence refreshed.")
            st.rerun()
        except ApiError as exc:
            render_api_error(exc, title="Intelligence refresh failed")

try:
    detail = client.get_json(
        f"/workspace/stock/{symbol}",
        params={"period": "6mo"},
        timeout=90,
    )
except ApiError as exc:
    render_api_error(exc, title=f"{symbol} detail unavailable")
    st.stop()

ohlc = detail.get("ohlc") if isinstance(detail.get("ohlc"), dict) else {}
q1, q2, q3, q4, q5 = st.columns(5)
with q1:
    st.metric("LTP", f"₹{float(detail.get('ltp') or 0):,.2f}")
with q2:
    st.metric("Open", f"₹{float(ohlc.get('open') or 0):,.2f}")
with q3:
    st.metric("High", f"₹{float(ohlc.get('high') or 0):,.2f}")
with q4:
    st.metric("Low", f"₹{float(ohlc.get('low') or 0):,.2f}")
with q5:
    st.metric("Prev close", f"₹{float(ohlc.get('previous_close') or 0):,.2f}")

candles = detail.get("candles")
candles = candles if isinstance(candles, list) else []
if candles:
    chart_frame = pd.DataFrame(candles)
    chart_frame["date"] = pd.to_datetime(chart_frame["date"], errors="coerce")
    chart_frame = chart_frame.dropna(subset=["date"])
    base = alt.Chart(chart_frame).encode(
        x=alt.X("date:T", title=None),
    )
    wick = base.mark_rule().encode(
        y=alt.Y("low:Q", title="Price"),
        y2="high:Q",
    )
    body = base.mark_bar(size=5).encode(
        y="open:Q",
        y2="close:Q",
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

news = detail.get("news") if isinstance(detail.get("news"), dict) else {}
actions = (
    detail.get("corporate_actions")
    if isinstance(detail.get("corporate_actions"), dict)
    else {}
)

news_tab, action_tab = st.tabs(["News", "Corporate actions"])
with news_tab:
    events = news.get("events")
    events = events if isinstance(events, list) else []
    if events:
        news_frame = pd.DataFrame(events)
        preferred = [
            "event_at",
            "headline",
            "sentiment_label",
            "impact_score",
            "source",
        ]
        st.dataframe(
            news_frame[[c for c in preferred if c in news_frame.columns]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No persisted news for this stock. Use Refresh intelligence.")

with action_tab:
    events = actions.get("events")
    events = events if isinstance(events, list) else []
    if events:
        action_frame = pd.DataFrame(events)
        preferred = [
            "event_at",
            "event_type",
            "headline",
            "impact_score",
            "source",
        ]
        st.dataframe(
            action_frame[[c for c in preferred if c in action_frame.columns]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No persisted corporate actions for this stock. Use Refresh intelligence.")
