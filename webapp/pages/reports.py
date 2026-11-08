"""Research batch history and automatic entry/exit reports."""

import streamlit as st

from webapp.report_workspace import render_batches, render_paper_reports
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import page_header

page_header(
    "Reports",
    "Batch progress, scanner evidence and completed trade entry/exit reports.",
    kicker="06 / Reports",
    show_legend=False,
)
if not admin_key_configured():
    st.info("An Admin API Key is required to view saved reports.")
    st.stop()
tabs = st.tabs(
    ["Research batches", "Paper statements"], key="reports_section", on_change="rerun"
)
client = api_client(timeout=30)
with tabs[0]:
    if tabs[0].open:
        render_batches(client)
with tabs[1]:
    if tabs[1].open:
        render_paper_reports(client)
