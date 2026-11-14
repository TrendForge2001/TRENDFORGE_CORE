"""Weekly research scanning; every run is stored as a report batch."""

import streamlit as st

from webapp.api_client import ApiError
from webapp.research_workspace import render_research_workspace
from webapp.runtime import admin_key_configured, api_client
from webapp.scanner_reference import render_scanner_reference
from webapp.ui import page_header, render_api_error

page_header(
    "Technical Scanner",
    "Select the stock list for the weekly strategy. Scan results are stored on Reports.",
    kicker="02 / Scanner",
)
client = api_client(timeout=30)
try:
    client.get_json("/technical/readiness")
except ApiError as exc:
    render_api_error(exc, title="Technical engine unavailable")
    st.stop()
render_research_workspace(
    client, authorized=admin_key_configured(), key="scanner", backtest=False
)
render_scanner_reference()
