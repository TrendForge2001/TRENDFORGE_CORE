"""Full-width content with optional controls, using ordinary page scrolling."""

import streamlit as st


def workspace_panels(key: str):
    if key == "paper":
        results = st.container(border=False, key="tf_paper_results")
        controls = st.container(border=False, key="tf_paper_controls")
        return controls, results
    controls = st.container(border=False, key=f"tf_{key}_controls")
    results = st.container(border=False, key=f"tf_{key}_results")
    return controls, results
