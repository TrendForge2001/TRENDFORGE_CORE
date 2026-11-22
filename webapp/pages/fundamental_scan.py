"""Reserved fundamental workspace; owner rules will be supplied later."""

import streamlit as st

from webapp.ui import page_header

page_header(
    "Fundamentals",
    "A dedicated space for your company-quality and valuation rules.",
    kicker="RESEARCH",
)
with st.container(border=True):
    st.subheader("Your fundamental screen is next")
    st.write(
        "This workspace is reserved for the conditions and data "
        "sources you will provide."
    )
    st.caption("No fundamental rating is inferred from technical or ownership data.")
