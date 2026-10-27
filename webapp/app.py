"""TrendForge Streamlit application entry point."""
from __future__ import annotations

import streamlit as st

from webapp.access import render_access_gate, revoke_access
from webapp.navigation import DEFAULT_PAGE, NAVIGATION_SPEC
from webapp.runtime import admin_key_configured, api_url, initialize_runtime
from webapp.ui import (
    apply_theme,
    render_brand,
    render_sidebar_status,
    render_workspace_bar,
)


st.set_page_config(
    page_title="TrendForge",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)
initialize_runtime()
apply_theme()

if not render_access_gate():
    st.stop()

with st.sidebar:
    render_brand()
    render_sidebar_status(
        api_endpoint=api_url(),
        admin_ready=admin_key_configured(),
    )
    st.markdown(
        '<div class="tf-sidebar-label">Workspace</div>',
        unsafe_allow_html=True,
    )

# Five first-level TOP tabs. Hidden legacy pages cannot execute.
pages = [
    st.Page(
        spec.path,
        title=spec.title,
        default=(spec.path == DEFAULT_PAGE),
    )
    for specs in NAVIGATION_SPEC.values()
    for spec in specs
]
navigation = st.navigation(pages, position="top")

with st.sidebar:
    st.divider()
    st.caption(
        "Technical trading workspace. "
        "Live broker orders require separate activation and risk review."
    )
    if st.button("Lock session", use_container_width=True):
        revoke_access()
        st.rerun()

render_workspace_bar()
navigation.run()
