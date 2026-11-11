"""Server-managed frontend API connection; credentials never enter widgets."""

from __future__ import annotations

import os

import streamlit as st

from webapp.api_client import TrendForgeApi


def initialize_runtime() -> None:
    # Ignore and remove old browser-session overrides. A server-held key must
    # only be sent to the backend configured by the operator on that server.
    st.session_state.pop("tf_api_url", None)
    st.session_state.pop("tf_admin_key", None)


def api_url() -> str:
    initialize_runtime()
    return os.getenv("TRENDFORGE_API_URL", "http://localhost:8000").strip()


def admin_key() -> str:
    initialize_runtime()
    return os.getenv("TRENDFORGE_ADMIN_API_KEY", "").strip()


def admin_key_configured() -> bool:
    return bool(admin_key())


def api_client(*, timeout: float = 30.0) -> TrendForgeApi:
    return TrendForgeApi(
        api_url(),
        admin_key(),
        default_timeout=timeout,
    )
