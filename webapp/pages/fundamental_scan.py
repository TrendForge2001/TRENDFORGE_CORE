"""Reserved fundamental workspace; owner rules will be supplied later."""

import streamlit as st

from webapp.ui import page_header

page_header("Fundamental Scanner", "Fundamental screening and strategy workspace.")
st.info(
    "Reserved for your fundamental conditions. Rules and data requirements are "
    "awaiting your details."
)
st.caption(
    "Technical scanning, backtesting, paper trading and reports are under "
    "TECHNICAL SCAN."
)
