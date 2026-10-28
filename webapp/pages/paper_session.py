"""Live paper-trading workspace with portfolio, risk controls and daily Excel P&L."""
from __future__ import annotations

import math

import pandas as pd

from webapp.trade_timestamps import format_trade_frame
import streamlit as st

from webapp.api_client import ApiError
from webapp.market_colours import market_frame
from webapp.paper_excel import paper_daily_xlsx, paper_statement_day, validate_daily_statement
from webapp.paper_policy import paper_entry_allowed, render_paper_entry_policy
from webapp.runtime import admin_key_configured, api_client
from webapp.workspace_layout import workspace_panels
from webapp.ui import page_header, render_api_error

page_header(
    "Live Paper Trading",
    "Simulated trading portfolio, saved-strategy automation, and strategy P&L statements.",
    kicker="04 / Paper Trading",
)
client = api_client(timeout=75)
controls, results_panel = workspace_panels("paper")
with controls:
    if st.button("Refresh paper readiness & positions"):
        st.rerun()
    paper_view = st.selectbox("Paper results", ["Open positions", "Daily P&L", "Strategy P&L", "Validation"])
    portfolio = None
    readiness = {}
    try:
        snapshot = client.get_json("/workspace/paper-portfolio")
        candidate = snapshot.get("portfolio")
        if (
            not isinstance(candidate, dict)
            or type(candidate.get("open_positions")) is not int
            or candidate["open_positions"] < 0
            or not isinstance(candidate.get("positions"), list)
            or not all(isinstance(row, dict) for row in candidate["positions"])
            or candidate["open_positions"] != len(candidate["positions"])
            or any(
                type(candidate.get(key)) not in {int, float}
                or not math.isfinite(candidate[key])
                for key in ("unrealized_pnl", "realized_pnl")
            )
        ):
            raise ApiError("Paper portfolio response is incomplete or invalid")
        portfolio = candidate
    except ApiError as exc:
        render_api_error(exc, title="Paper portfolio unavailable")
    try:
        readiness = client.get_json("/paper/readiness")
    except ApiError as exc:
        render_api_error(exc, title="Paper-entry readiness unavailable")

    can_enter = (
        portfolio is not None
        and paper_entry_allowed(readiness)
        and admin_key_configured()
    )
    render_paper_entry_policy(readiness)

    a, b, c, d = results_panel.columns(4)
    a.metric("Open positions", portfolio["open_positions"] if portfolio is not None else "Unavailable")
    b.metric("Unrealized P&L (last marks)", f"₹{portfolio['unrealized_pnl']:,.2f}" if portfolio is not None else "Unavailable")
    c.metric("Lifetime realized P&L", f"₹{portfolio['realized_pnl']:,.2f}" if portfolio is not None else "Unavailable")
    d.metric("Kill switch", ("ON" if readiness["kill_switch"] else "OFF") if type(readiness.get("kill_switch")) is bool else "Unavailable")
    monitor = readiness.get("automatic_monitor")
    monitor = monitor if isinstance(monitor, dict) else {}
    results_panel.caption("Unrealized P&L uses the last saved position marks, which can be stale or reset to entry on restoration. A successful monitor poll does not establish exchange-quote freshness.")
    if not readiness:
        st.warning("Automatic quote-monitor status is unavailable. Saved P&L marks may be stale.")
    elif monitor.get("enabled") is not True or monitor.get("running") is not True:
        st.warning("Automatic quote monitoring is disabled or stopped. Saved P&L marks may be stale; use the paper quote/SL monitor to update them.")
    elif monitor.get("last_error"):
        st.warning("The last automatic quote-monitor attempt failed. Saved P&L marks may be stale.")
    if monitor.get("last_success_at"):
        st.caption(f"Last successful monitor poll: {monitor['last_success_at']}")
with results_panel:
    positions = portfolio["positions"] if portfolio is not None else None
    if paper_view == "Open positions":
        st.subheader("Paper portfolio — open positions")
    if paper_view != "Open positions":
        pass
    elif positions is None:
        st.info("Paper positions are unavailable until the portfolio can be loaded.")
    elif positions:
        st.dataframe(market_frame(format_trade_frame(pd.DataFrame(positions))), width="stretch", hide_index=True)
    else:
        st.info("No open paper positions.")

with results_panel:
    if paper_view == "Daily P&L":
        st.subheader("Daily paper P&L statement")
    try:
        statement = client.get_json("/pnl", params={"period": "daily"})
    except ApiError as exc:
        render_api_error(exc, title="Daily P&L ledger unavailable")
        statement = None

    if portfolio is None:
        st.info("Daily P&L totals and export are unavailable until the paper portfolio can be loaded.")
        statement = None
    elif statement is not None:
        try:
            validate_daily_statement(statement, portfolio)
        except ValueError:
            st.error("The daily paper P&L response is incomplete or invalid; statement totals and export are unavailable.")
            statement = None

    if statement is not None and paper_view == "Daily P&L":
        summary = statement["summary"]
        q1, q2, q3 = st.columns(3)
        q1.metric("Today's realized P&L", f"₹{float(summary.get('net_pnl') or 0):,.2f}")
        q2.metric("Today's closed trades", int(summary.get("trade_count") or 0))
        q3.metric("Open unrealized P&L (last marks)", f"₹{float(portfolio.get('unrealized_pnl') or 0):,.2f}")
        st.caption("Realized daily P&L counts closed trades by exit date (legacy records may use their entry date). Open unrealized P&L uses last saved marks, not today's incremental price movement.")
        trades = statement.get("trades") or []
        if isinstance(trades, list) and trades:
            st.dataframe(market_frame(format_trade_frame(pd.DataFrame(trades))), hide_index=True, width="stretch")
        else:
            st.info("No paper trades closed today.")
        try:
            exported = paper_daily_xlsx(statement, portfolio)
            date = paper_statement_day(statement)
            controls.download_button(
                "Download daily P&L statement (.xlsx)", exported,
                file_name=f"trendforge_paper_pnl_{date}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
        except (ValueError, TypeError, ImportError):
            st.error("Excel export is unavailable for this statement.")

from webapp.paper_automation import render_paper_automation

with controls:
    render_paper_automation(client, results=results_panel, view=paper_view)

with controls, st.expander("Supervised paper entry", expanded=False):
    with st.form("tf_r726_paper_entry"):
        symbol = st.text_input("NSE symbol", value="RELIANCE").strip().upper()
        side = st.selectbox("Paper side", ["BUY", "SHORT"])
        qty = st.number_input("Quantity", min_value=1, value=1)
        price = st.number_input("Simulated entry (₹)", min_value=0.01, value=100.0, step=0.05)
        stop = st.number_input("Stop loss (₹)", min_value=0.0, value=0.0)
        target = st.number_input("Target (₹)", min_value=0.0, value=0.0)
        submit = st.form_submit_button("Open paper position", disabled=not can_enter)
    if submit:
        if not can_enter:
            st.error("New paper entries are currently disabled.")
        else:
            try:
                client.post_json("/paper/open", {
                    "symbol": symbol, "side": side, "quantity": int(qty),
                    "price": float(price), "stoploss": float(stop), "target2": float(target),
                })
                st.success("Simulated paper position submitted.")
                st.rerun()
            except ApiError as exc:
                render_api_error(exc, title="Paper entry rejected")
with controls, st.expander("Paper risk controls", expanded=False):
    st.caption("Kill controls and manual monitoring")
    if not admin_key_configured():
        st.warning("The Admin API Key is required for paper mutations.")
    if st.button("Activate paper kill switch", disabled=not admin_key_configured(), width="stretch"):
        try:
            client.post_json("/paper/kill-switch", {"enabled": True})
            st.rerun()
        except ApiError as exc:
            render_api_error(exc)
    if st.button("Release paper kill switch", disabled=not admin_key_configured(), width="stretch"):
        try:
            client.post_json("/paper/kill-switch", {"enabled": False})
            st.rerun()
        except ApiError as exc:
            render_api_error(exc)
    if st.button("Run paper quote/SL monitor", disabled=not admin_key_configured(), width="stretch"):
        try:
            st.json(client.post_json("/paper/monitor/tick", {}, timeout=90))
            st.rerun()
        except ApiError as exc:
            render_api_error(exc)
    if st.button("Run strategy exit check", disabled=not admin_key_configured(), width="stretch"):
        try:
            st.json(client.post_json("/paper/strategy-monitor/tick", {}, timeout=120))
        except ApiError as exc:
            render_api_error(exc)
