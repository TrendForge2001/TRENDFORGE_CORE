"""Authenticated Kite session monitoring and broker trading safety view."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import page_header, render_api_error

page_header(
    "Live Kite Session",
    "Authenticated Kite account session, live broker positions and orders, with broker execution guarded.",
    kicker="05 / Live Kite",
)
client = api_client(timeout=60)
if not admin_key_configured():
    st.warning("Enter the Admin API Key at sign-in to inspect the protected Kite broker session.")
    st.stop()

if st.button("Refresh Kite session", use_container_width=False):
    st.rerun()

try:
    data = client.get_json("/workspace/kite-session", timeout=60)
except ApiError as exc:
    render_api_error(exc, title="Kite broker session unavailable")
    st.stop()

s1, s2, s3 = st.columns(3)
s1.metric("Session", str(data.get("status") or "unavailable").upper())
s2.metric("Authenticated", "YES" if data.get("authenticated") else "NO")
s3.metric("Live broker orders", "ENABLED" if data.get("broker_orders_allowed") else "LOCKED")
if not data.get("authenticated"):
    st.warning("Kite access token is missing or expired. Update the authorized token in the backend environment; broker actions remain locked.")
    st.stop()
st.caption("Kite sessions require fresh daily authentication. Never paste Kite API keys or access tokens into this webapp.")

holdings = data.get("holdings")
st.subheader("Kite delivery holdings")
if isinstance(holdings, list) and holdings:
    st.dataframe(pd.DataFrame(holdings), use_container_width=True, hide_index=True)
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
            st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
        else:
            st.info("No broker positions in this book.")
else:
    st.info("Kite position data is unavailable.")
orders = data.get("orders")
st.subheader("Recent Kite orders")
if isinstance(orders, list) and orders:
    st.dataframe(pd.DataFrame(orders), use_container_width=True, hide_index=True)
else:
    st.info("No recent Kite orders returned.")

st.divider()
st.subheader("Live execution")
st.warning(
    "Real-money broker order entry is not activated through this page. "
    "The existing broker write guard remains enforced; a separate, audited "
    "manual order ticket, server-side risk admission and explicit enablement "
    "are required before order placement."
)
