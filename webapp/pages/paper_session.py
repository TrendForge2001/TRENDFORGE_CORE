"""Live paper-trading workspace with portfolio, risk controls and daily Excel P&L."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.paper_excel import paper_daily_xlsx
from webapp.paper_policy import paper_entry_allowed, render_paper_entry_policy
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import page_header, render_api_error

page_header(
    "Live Paper Trading",
    "Simulated trading portfolio, supervised entries and exits, and a daily Excel P&L statement.",
    kicker="04 / Paper Trading",
)
client = api_client(timeout=75)
try:
    snapshot = client.get_json("/workspace/paper-portfolio")
    readiness = client.get_json("/paper/readiness")
except ApiError as exc:
    render_api_error(exc, title="Paper trading runtime unavailable")
    st.stop()

portfolio = snapshot.get("portfolio")
portfolio = portfolio if isinstance(portfolio, dict) else {}
can_enter = paper_entry_allowed(readiness) and admin_key_configured()
render_paper_entry_policy(readiness)

a, b, c, d = st.columns(4)
a.metric("Open positions", int(portfolio.get("open_positions") or 0))
b.metric("Current unrealized P&L", f"₹{float(portfolio.get('unrealized_pnl') or 0):,.2f}")
c.metric("Lifetime realized P&L", f"₹{float(portfolio.get('realized_pnl') or 0):,.2f}")
d.metric("Kill switch", "ON" if readiness.get("kill_switch") else "OFF")
positions = portfolio.get("positions")
positions = positions if isinstance(positions, list) else []
st.subheader("Paper portfolio — open positions")
if positions:
    st.dataframe(pd.DataFrame(positions), use_container_width=True, hide_index=True)
else:
    st.info("No open paper positions.")

st.subheader("Daily paper P&L statement")
try:
    statement = client.get_json("/pnl", params={"period": "daily"})
except ApiError as exc:
    render_api_error(exc, title="Daily P&L ledger unavailable")
    statement = None

if isinstance(statement, dict) and statement.get("scope") == "paper_trading_closed_trades":
    summary = statement.get("summary") or {}
    q1, q2, q3 = st.columns(3)
    q1.metric("Today's realized P&L", f"₹{float(summary.get('net_pnl') or 0):,.2f}")
    q2.metric("Today's closed trades", int(summary.get("trade_count") or 0))
    q3.metric("Current open unrealized P&L", f"₹{float(portfolio.get('unrealized_pnl') or 0):,.2f}")
    st.caption("Realized daily P&L counts closed trades by exit date (legacy records may use their entry date). Open unrealized P&L is current mark-to-market, not today's incremental price movement.")
    trades = statement.get("trades") or []
    if isinstance(trades, list) and trades:
        st.dataframe(pd.DataFrame(trades), hide_index=True, use_container_width=True)
    else:
        st.info("No paper trades closed today.")
    try:
        exported = paper_daily_xlsx(statement, portfolio)
        date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        st.download_button(
            "Download daily P&L statement (.xlsx)", exported,
            file_name=f"trendforge_paper_pnl_{date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    except (ValueError, TypeError, ImportError) as exc:
        st.error("Excel export is unavailable. Check the installed workbook engine.")

st.divider()
left, right = st.columns([3, 2])
with left:
    st.subheader("Supervised paper entry")
    with st.form("tf_r726_paper_entry"):
        symbol = st.text_input("NSE symbol", value="RELIANCE").strip().upper()
        side = st.selectbox("Paper side", ["BUY", "SELL", "SHORT"])
        qty = st.number_input("Quantity", min_value=1, value=1)
        price = st.number_input("Simulated entry (₹)", min_value=0.01, value=100.0, step=0.05)
        stop = st.number_input("Stop loss (₹)", min_value=0.0, value=0.0)
        target = st.number_input("Target (₹)", min_value=0.0, value=0.0)
        submit = st.form_submit_button("Open paper position", disabled=not can_enter)
    if submit:
        try:
            client.post_json("/paper/open", {
                "symbol": symbol, "side": side, "quantity": int(qty),
                "price": float(price), "stoploss": float(stop), "target2": float(target),
            })
            st.success("Simulated paper position submitted.")
            st.rerun()
        except ApiError as exc:
            render_api_error(exc, title="Paper entry rejected")
with right:
    st.subheader("Paper risk controls")
    if not admin_key_configured():
        st.warning("The Admin API Key is required for paper mutations.")
    if st.button("Activate paper kill switch", disabled=not admin_key_configured(), use_container_width=True):
        try:
            client.post_json("/paper/kill-switch", {"enabled": True})
            st.rerun()
        except ApiError as exc:
            render_api_error(exc)
    if st.button("Release paper kill switch", disabled=not admin_key_configured(), use_container_width=True):
        try:
            client.post_json("/paper/kill-switch", {"enabled": False})
            st.rerun()
        except ApiError as exc:
            render_api_error(exc)
    if st.button("Run paper quote/SL monitor", disabled=not admin_key_configured(), use_container_width=True):
        try:
            st.json(client.post_json("/paper/monitor/tick", {}, timeout=90))
            st.rerun()
        except ApiError as exc:
            render_api_error(exc)
    if st.button("Run strategy exit check", disabled=not admin_key_configured(), use_container_width=True):
        try:
            st.json(client.post_json("/paper/strategy-monitor/tick", {}, timeout=120))
        except ApiError as exc:
            render_api_error(exc)
