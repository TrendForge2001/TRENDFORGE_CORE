"""Authenticated Kite session monitoring and broker trading safety view."""
from __future__ import annotations

import pandas as pd

from webapp.trade_timestamps import format_trade_frame
import streamlit as st

from webapp.api_client import ApiError
from webapp.market_colours import market_frame
from webapp.runtime import admin_key_configured, api_client
from webapp.workspace_layout import workspace_panels
from webapp.ui import page_header, render_api_error

page_header(
    "Live Kite Session",
    "Authenticated Kite account session, live broker positions and orders, with broker execution guarded.",
    kicker="05 / Live Kite",
)
client = api_client(timeout=60)
controls, results_panel = workspace_panels("kite")
with controls:
    if not admin_key_configured():
        st.warning("Enter the Admin API Key at sign-in to inspect the protected Kite broker session.")
        st.stop()

    if st.button("Refresh Kite session", width="content"):
        st.rerun()


    with st.expander("Live Kite trading preparation", expanded=True):
        st.caption("Read-only checks for a future order workflow. Authentication alone does not make this app ready to submit live orders.")
        if st.button("Check Kite trading readiness"):
            try:
                report = client.get_json("/workspace/kite-trading-readiness", params={"probe_quotes": True, "probe_history": True}, timeout=60)
                results_panel.dataframe(pd.DataFrame(report["checks"]), hide_index=True, width="stretch")
                st.info(report["notes"])
            except ApiError as exc:
                render_api_error(exc, title="Live trading preparation check unavailable")


    try:
        data = client.get_json("/workspace/kite-session", timeout=60)
    except ApiError as exc:
        render_api_error(exc, title="Kite broker session unavailable")
        st.stop()

    s1, s2 = st.columns(2)
    s1.metric("Session", str(data.get("status") or "unavailable").upper())
    s2.metric("Authenticated", "YES" if data.get("authenticated") else "NO")
    st.caption("Live broker orders: " + ("ENABLED" if data.get("broker_orders_allowed") else "LOCKED"))
    if not data.get("authenticated"):
        from providers.kite_diagnostics import safe_session_failure
        diagnostic = data.get("diagnostic")
        diagnostic = diagnostic if isinstance(diagnostic, dict) else {}
        failure = safe_session_failure({
            "auth_error_code": diagnostic.get("code"),
            "auth_http_status": diagnostic.get("http_status"),
        })
        st.warning(failure["message"])
        st.caption(f"Session diagnostic: {failure['code']}")
        if failure["http_status"] is not None:
            st.caption(f"Kite HTTP status: {failure['http_status']}")
        st.info("Update the authorized Kite session on the running backend. Render credentials must be updated in Render’s environment settings and deployed. Never share credentials.")
        st.stop()
    st.caption("Kite sessions require fresh daily authentication. Never paste Kite API keys or access tokens into this webapp.")

with results_panel:
    holdings = data.get("holdings")
    st.subheader("Kite delivery holdings")
    if isinstance(holdings, list) and holdings:
        st.dataframe(market_frame(format_trade_frame(pd.DataFrame([{**row, "signal": "HOLD"} for row in holdings]))), width="stretch", hide_index=True)
    else:
        st.info("No delivery holdings returned by the Kite broker session.")

    margins = data.get("margins")
    if isinstance(margins, dict):
        with st.expander("Broker margin details", expanded=False):
            st.json(margins)
    positions = data.get("positions")
    if isinstance(positions, dict):
        for label in ("net", "day"):
            records = positions.get(label)
            st.subheader(f"Kite {label.title()} positions")
            if isinstance(records, list) and records:
                st.dataframe(market_frame(format_trade_frame(pd.DataFrame(records))), width="stretch", hide_index=True)
            else:
                st.info("No broker positions in this book.")
    else:
        st.info("Kite position data is unavailable.")
    orders = data.get("orders")
    st.subheader("Recent Kite orders")
    if isinstance(orders, list) and orders:
        st.dataframe(market_frame(format_trade_frame(pd.DataFrame(orders))), width="stretch", hide_index=True)
    else:
        st.info("No recent Kite orders returned.")

with controls:
    st.divider()
    st.subheader("Live execution")
    st.warning(
        "Real-money broker order entry is not activated through this page. "
        "The existing broker write guard remains enforced; a separate, audited "
        "manual order ticket, server-side risk admission and explicit enablement "
        "are required before order placement."
    )
