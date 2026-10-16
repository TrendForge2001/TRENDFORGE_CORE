"""Simple session access gate for the Streamlit control plane."""
from __future__ import annotations

import os
import secrets

import streamlit as st


ACCESS_ENV = "TRENDFORGE_WEBAPP_ACCESS_KEY"


def configured_access_key() -> str:
    return os.getenv(ACCESS_ENV, "").strip()


def access_required() -> bool:
    return bool(configured_access_key())


def access_granted() -> bool:
    if not access_required():
        return True
    return bool(st.session_state.get("tf_access_granted"))


def render_access_gate() -> bool:
    """Render a password gate and return whether the session is authorized."""
    expected = configured_access_key()
    if not expected:
        return True
    if access_granted():
        return True

    st.markdown("## TrendForge Control Plane")
    st.caption(
        "This deployment is protected because it can invoke "
        "admin-key-gated TrendForge operations."
    )
    with st.form("tf_access_gate", clear_on_submit=True):
        supplied = st.text_input(
            "Webapp access key",
            type="password",
        )
        submitted = st.form_submit_button(
            "Unlock",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if secrets.compare_digest(
            supplied.strip(),
            expected,
        ):
            st.session_state["tf_access_granted"] = True
            st.rerun()
        st.error("Access key rejected.")
    return False


def revoke_access() -> None:
    st.session_state["tf_access_granted"] = False
