"""A bounded, cached Core API liveness check, separate from broker readiness."""

import streamlit as st

from webapp.api_client import ApiError, TrendForgeApi


@st.cache_data(ttl=30, show_spinner=False)
def core_status(endpoint: str) -> tuple[str, str]:
    try:
        result = TrendForgeApi(endpoint, default_timeout=2).get_json(
            "/livez", timeout=2
        )
        if result.get("status") == "ok" and result.get("service") == "TrendForge Core":
            return "Connected", "tf-dot-green"
    except (ApiError, ValueError):
        pass
    return "Unavailable", "tf-dot-amber"
