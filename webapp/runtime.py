"""Session-scoped frontend runtime configuration."""
from __future__ import annotations

import os

import streamlit as st

from webapp.api_client import TrendForgeApi


DEFAULT_API_URL = os.getenv(
    "TRENDFORGE_API_URL",
    "http://localhost:8000",
).strip()
ENV_ADMIN_KEY = os.getenv("TRENDFORGE_ADMIN_API_KEY", "").strip()


def initialize_runtime() -> None:
    st.session_state.setdefault("tf_api_url", DEFAULT_API_URL)
    st.session_state.setdefault("tf_admin_key", ENV_ADMIN_KEY)


def api_url() -> str:
    initialize_runtime()
    return str(st.session_state["tf_api_url"]).strip()


def admin_key() -> str:
    initialize_runtime()
    return str(st.session_state["tf_admin_key"]).strip()


def admin_key_configured() -> bool:
    return bool(admin_key())


def api_client(*, timeout: float = 30.0) -> TrendForgeApi:
    return TrendForgeApi(
        api_url(),
        admin_key(),
        default_timeout=timeout,
    )
