"""Shared-cash Kite historical portfolio backtesting in the existing tab."""

import streamlit as st

from webapp.api_client import ApiError
from webapp.portfolio_backtesting import render_portfolio_backtesting
from webapp.runtime import admin_key_configured, api_client
from webapp.strategy_catalog import clear_retired_scan_cache
from webapp.ui import page_header, render_api_error

page_header(
    "Kite Historical Backtesting",
    "Choose a stock list and backtesting period. Entry/exit reports appear automatically on Reports.",
    kicker="03 / Backtesting",
)
clear_retired_scan_cache()
client = api_client(timeout=240)
try:
    client.get_json("/technical/readiness")
except ApiError as exc:
    render_api_error(exc, title="Kite technical history unavailable")
    st.stop()
render_portfolio_backtesting(client, authorized=admin_key_configured())
