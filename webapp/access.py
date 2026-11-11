"""Fail-closed, session-scoped access gate for the Streamlit control plane.

The access key is the only sign-in credential. The separate admin API key
stays in the server environment and is never entered or displayed in the app.
"""

from __future__ import annotations

import hashlib
import os
import secrets

import streamlit as st

ACCESS_ENV = "TRENDFORGE_WEBAPP_ACCESS_KEY"


def configured_access_key() -> str:
    return os.getenv(ACCESS_ENV, "").strip()


def access_required() -> bool:
    """The Streamlit control plane must always be locked before login."""
    return True


def _access_fingerprint(expected: str) -> str:
    """Session marker that becomes invalid when the server key rotates."""
    return hashlib.sha256(expected.encode("utf-8")).hexdigest()


def access_granted() -> bool:
    expected = configured_access_key()
    if not expected:
        return False
    fingerprint = st.session_state.get("tf_access_fingerprint", "")
    return bool(
        st.session_state.get("tf_access_granted")
        and isinstance(fingerprint, str)
        and secrets.compare_digest(fingerprint, _access_fingerprint(expected))
    )


def render_access_gate() -> bool:
    """Return True only after the configured webapp access key was entered."""
    expected = configured_access_key()
    if not expected:
        st.error(
            "TrendForge is locked: TRENDFORGE_WEBAPP_ACCESS_KEY is not "
            "configured on this service. Set it in Render Environment. "
            "An empty access key cannot unlock this application."
        )
        return False

    if access_granted():
        return True

    # If an earlier session was unlocked before access-key rotation, invalidate
    # the old credentials before presenting the new login form.
    if st.session_state.get("tf_access_granted"):
        revoke_access()

    st.markdown("## TrendForge — Secure Sign In")
    st.caption(
        "Enter your webapp access key to open your workspace. "
        "The API connection is managed securely on the server."
    )
    with st.form("tf_access_gate", clear_on_submit=True):
        supplied = st.text_input(
            "Webapp access key",
            type="password",
            help="Type the access key provided for this webapp.",
        )
        submitted = st.form_submit_button(
            "Open TrendForge",
            type="primary",
            width="stretch",
        )

    if submitted:
        if supplied.strip() and secrets.compare_digest(supplied.strip(), expected):
            st.session_state["tf_access_fingerprint"] = _access_fingerprint(expected)
            st.session_state["tf_access_granted"] = True
            # Remove legacy session credentials; API auth stays server-side.
            st.session_state.pop("tf_admin_key", None)
            st.rerun()
        else:
            st.error("Invalid webapp access key. Access denied.")
    return False


def revoke_access() -> None:
    """Lock the app and clear TrendForge session credentials and results."""
    for name in list(st.session_state):
        if str(name).startswith("tf_"):
            del st.session_state[name]
