"""Research batch history and automatic entry/exit reports."""

import streamlit as st

from core.deployment_role import cloud_read_only
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
if cloud_read_only():
    st.warning(
        "Cloud reports are temporary and can disappear after a restart. Use "
        "the PC workspace for permanent reports, or copy completed cloud "
        "reports to the PC with Save-TrendForgeReports.ps1."
    )
else:
    st.caption(
        "Completed reports are saved automatically in the PC data folder "
        "and remain available after an application restart."
    )
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
