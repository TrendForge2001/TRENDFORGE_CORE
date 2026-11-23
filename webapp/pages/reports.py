"""Automatically retained scanner reports; paper and backtests stay separate."""

import streamlit as st

from webapp.runtime import admin_key_configured, api_client
from webapp.scanner_workflow_workspace import scanner_reports
from webapp.ui import page_header

page_header(
    "Reports",
    "Every stock signal from your latest scanner runs.",
    kicker="SCANNER REPORTS",
    show_legend=False,
)
if not admin_key_configured():
    st.info("The operator must configure API authentication on the server.")
    st.stop()
scanner_reports(api_client(timeout=30))
