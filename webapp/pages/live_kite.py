"""Authenticated Kite session monitoring and broker trading safety view."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.market_colours import market_frame
from webapp.runtime import admin_key_configured, api_client
from webapp.trade_timestamps import format_trade_frame
from webapp.ui import page_header, render_api_error
from webapp.workspace_layout import workspace_panels

page_header(
    "Live Kite Session",
    "Authenticated Kite account session, live broker positions and orders, "
    "with broker execution guarded.",
    kicker="05 / Live Kite",
)
client = api_client(timeout=60)
controls, results_panel = workspace_panels("kite")
with controls:
    if not admin_key_configured():
        st.warning(
            "Enter the Admin API Key at sign-in to inspect the protected "
            "Kite broker session."
        )
        st.stop()

    if st.button("Refresh Kite session", width="content"):
        st.rerun()

    with st.expander("Kite API network and IP whitelist", expanded=False):
        st.caption(
            "Order APIs require a provisioned static outbound IP registered in "
            "Kite Connect Developer Console → Profile → IP Whitelist. "
            "The website URL and login redirect do not provide that IP."
        )
        if st.button("Check outbound IP — no trade"):
            try:
                network = client.get_json(
                    "/workspace/kite-network-readiness",
                    params={"probe": True},
                    timeout=45,
                )
                st.write("Network status: " + network["status"])
                st.write("Observed IPs:", network.get("observed_ips", []))
                st.write("Configured IPs:", network.get("expected_ips", []))
                if network["status"] == "fixed_egress_not_configured":
                    st.warning(
                        "Fixed outbound routing has not been provisioned and "
                        "configured on this server. No IP was allocated by this check."
                    )
                st.caption(network["notes"])
            except ApiError as exc:
                render_api_error(exc, title="Kite network check unavailable")

    with st.expander("Live Kite trading preparation", expanded=False):
        st.caption(
            "Read-only checks for a future order workflow. Authentication alone "
            "does not make this app ready to submit live orders."
        )
        if st.button("Check Kite trading readiness"):
            try:
                report = client.get_json(
                    "/workspace/kite-trading-readiness",
                    params={"probe_quotes": True, "probe_history": True},
                    timeout=60,
                )
                results_panel.dataframe(
                    pd.DataFrame(report["checks"]), hide_index=True, width="stretch"
                )
                st.info(report["notes"])
            except ApiError as exc:
                render_api_error(
                    exc, title="Live trading preparation check unavailable"
                )
        with st.form("kite_read_only_preview"):
            st.caption("Preview only. This form cannot submit an order.")
            st.caption(
                "BUY: stop price < fresh quote < target price. "
                "SHORT: target price < fresh quote < stop price. "
                "Enter your own prices; both must match the instrument tick size."
            )
            preview_symbol = st.text_input("NSE equity symbol", value="RELIANCE")
            preview_side = st.radio("Direction", ("BUY", "SHORT"), horizontal=True)
            preview_product = st.radio("Product", ("MIS", "CNC"), horizontal=True)
            preview_quantity = st.number_input(
                "Quantity", min_value=1, max_value=1000000, value=1
            )
            preview_stop = st.number_input(
                "Stop price",
                min_value=0.01,
                value=None,
                step=0.01,
                placeholder="Enter stop price",
            )
            preview_target = st.number_input(
                "Target price",
                min_value=0.01,
                value=None,
                step=0.01,
                placeholder="Enter target price",
            )
            preview_clicked = st.form_submit_button("Preview with fresh quote")
        if preview_clicked and (preview_stop is None or preview_target is None):
            st.warning("Enter both a stop price and a target price to preview.")
        elif preview_clicked:
            try:
                preview = client.post_json(
                    "/workspace/kite/order-preview",
                    payload={
                        "symbol": preview_symbol.strip().upper(),
                        "side": preview_side,
                        "product": preview_product,
                        "quantity": preview_quantity,
                        "stoploss": preview_stop,
                        "target": preview_target,
                    },
                    timeout=60,
                )
                st.json(preview)
                st.info("Read-only preview generated. Real orders remain disabled.")
            except ApiError as exc:
                render_api_error(exc, title="Order preview unavailable")

    try:
        data = client.get_json("/workspace/kite-session", timeout=60)
    except ApiError as exc:
        render_api_error(exc, title="Kite broker session unavailable")
        st.stop()

    s1, s2 = st.columns(2)
    s1.metric("Session", str(data.get("status") or "unavailable").upper())
    s2.metric("Authenticated", "YES" if data.get("authenticated") else "NO")
    st.caption(
        "Live broker orders: "
        + ("ENABLED" if data.get("broker_orders_allowed") else "LOCKED")
    )
    if not data.get("authenticated"):
        from providers.kite_diagnostics import safe_session_failure

        diagnostic = data.get("diagnostic")
        diagnostic = diagnostic if isinstance(diagnostic, dict) else {}
        failure = safe_session_failure(
            {
                "auth_error_code": diagnostic.get("code"),
                "auth_http_status": diagnostic.get("http_status"),
            }
        )
        st.warning(failure["message"])
        st.caption(f"Session diagnostic: {failure['code']}")
        if failure["http_status"] is not None:
            st.caption(f"Kite HTTP status: {failure['http_status']}")
        st.info(
            "Update the authorized Kite session on the running backend. Render "
            "credentials must be updated in Render’s environment settings and "
            "deployed. Never share credentials."
        )
        st.stop()
    st.caption(
        "Kite sessions require fresh daily authentication. Never paste Kite API "
        "keys or access tokens into this webapp."
    )

with results_panel:
    holdings = data.get("holdings")
    st.subheader("Kite delivery holdings")
    if isinstance(holdings, list) and holdings:
        st.dataframe(
            market_frame(
                format_trade_frame(
                    pd.DataFrame([{**row, "signal": "HOLD"} for row in holdings])
                )
            ),
            width="stretch",
            hide_index=True,
        )
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
                st.dataframe(
                    market_frame(format_trade_frame(pd.DataFrame(records))),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("No broker positions in this book.")
    else:
        st.info("Kite position data is unavailable.")
    orders = data.get("orders")
    st.subheader("Recent Kite orders")
    if isinstance(orders, list) and orders:
        st.dataframe(
            market_frame(format_trade_frame(pd.DataFrame(orders))),
            width="stretch",
            hide_index=True,
        )
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
