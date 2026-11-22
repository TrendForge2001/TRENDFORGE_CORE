"""Research batch history and automatic entry/exit reports."""

import streamlit as st

from webapp.policy_validation_report import render_policy_validation
from webapp.report_workspace import render_batches, render_paper_reports
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import page_header

page_header(
    "Reports",
    "Research results, coverage and paper statements in one place.",
    kicker="RESEARCH & PAPER",
    show_legend=False,
)
if not admin_key_configured():
    st.info("The operator must configure API authentication on the server.")
    st.stop()
tabs = st.tabs(
    ["Research batches", "Paper statements", "Policy validation", "Stock report"],
    key="reports_section",
    on_change="rerun",
)
client = api_client(timeout=30)
with tabs[0]:
    if tabs[0].open:
        render_batches(client)
with tabs[1]:
    if tabs[1].open:
        render_paper_reports(client)
with tabs[2]:
    if tabs[2].open:
        render_policy_validation(client)

with tabs[3]:
    if tabs[3].open:
        from webapp.stock_report_workspace import render_stock_report_workspace

        render_stock_report_workspace(client)
