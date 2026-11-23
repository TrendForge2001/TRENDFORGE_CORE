"""Weekly research scanning; every run is stored as a report batch."""

import streamlit as st

from webapp.api_client import ApiError
from webapp.research_workspace import render_research_workspace
from webapp.runtime import admin_key_configured, api_client, api_url
from webapp.stock_lists import render_shared_stock_lists
from webapp.ui import page_header, render_api_error

page_header(
    "Stock Scanner",
    "Technical signals, institutional activity and data coverage in one stock view.",
    kicker="02 / Scanner",
)
client = api_client(timeout=30)
render_shared_stock_lists(api_url())
try:
    client.get_json("/technical/readiness")
except ApiError as exc:
    render_api_error(exc, title="Technical engine unavailable")
    st.stop()
tabs = st.tabs(
    ["Scan stocks", "Stock report"], key="scanner_section", on_change="rerun"
)
with tabs[0]:
    if tabs[0].open:
        render_research_workspace(
            client, authorized=admin_key_configured(), key="scanner", backtest=False
        )
with tabs[1]:
    if tabs[1].open:
        from webapp.stock_report_workspace import render_stock_report_workspace

        render_stock_report_workspace(client)
