"""Two compact, independently scrollable workspace panels."""

import streamlit as st


def workspace_panels(key: str):
    left, right = st.columns([1, 2.4], gap="small")
    controls = left.container(height=610, border=True, key=f"tf_{key}_controls")
    results = right.container(height=610, border=True, key=f"tf_{key}_results")
    return controls, results
