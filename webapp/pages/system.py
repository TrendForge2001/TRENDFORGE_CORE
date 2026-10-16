"""Frontend connection and backend system diagnostics."""
from __future__ import annotations

import streamlit as st

from webapp.access import access_required, revoke_access
from webapp.api_client import ApiError, TrendForgeApi
from webapp.runtime import (
    admin_key,
    api_url,
    initialize_runtime,
)
from webapp.ui import (
    info_note,
    page_header,
    render_api_error,
)


initialize_runtime()
page_header(
    "System",
    "Configure the frontend-to-API connection for this browser session and inspect production diagnostics without writing secrets to the repository.",
    kicker="Administration",
)

with st.form("runtime_settings"):
    new_url = st.text_input(
        "TrendForge API URL",
        value=api_url(),
    )
    new_key = st.text_input(
        "Admin API key",
        value=admin_key(),
        type="password",
        help=(
            "Stored only in this Streamlit browser session "
            "unless supplied through the process environment."
        ),
    )
    saved = st.form_submit_button(
        "Save session settings",
        type="primary",
    )

if saved:
    st.session_state["tf_api_url"] = (
        new_url.strip().rstrip("/")
    )
    st.session_state["tf_admin_key"] = new_key.strip()
    st.success("Session settings updated.")

col1, col2, col3 = st.columns(3)
with col1:
    if st.button(
        "Clear session admin key",
        use_container_width=True,
    ):
        st.session_state["tf_admin_key"] = ""
        st.rerun()

with col2:
    if st.button(
        "Test API connection",
        use_container_width=True,
    ):
        try:
            payload = TrendForgeApi(
                api_url(),
                admin_key(),
            ).get_json("/health")
            st.success("API connection is healthy.")
            st.json(payload)
        except (ApiError, ValueError) as exc:
            st.error(str(exc))

with col3:
    if access_required():
        if st.button(
            "Lock webapp session",
            use_container_width=True,
        ):
            revoke_access()
            st.rerun()
    else:
        st.caption("Webapp access gate: local/unconfigured")

info_note(
    "Recommended deployment: keep the FastAPI backend and Streamlit frontend as separate services. The frontend should receive TRENDFORGE_API_URL and, only where needed, TRENDFORGE_ADMIN_API_KEY through service secrets."
)

st.divider()
st.subheader("Diagnostics")

try:
    client = TrendForgeApi(api_url(), admin_key())
except ValueError as exc:
    st.error(str(exc))
    st.stop()

for title, path in (
    ("Production health", "/production/health"),
    ("Core health", "/health"),
    ("Scan runtime", "/observability/scan-runtime"),
    ("Paper readiness", "/paper/readiness"),
    (
        "Paper auto-entry readiness",
        "/paper/auto-entry/readiness",
    ),
    ("Portfolio snapshot", "/portfolio"),
    ("Monthly P&L", "/pnl?period=monthly"),
    (
        "Monthly performance",
        "/performance?period=monthly",
    ),
    ("Watchlists", "/watchlists"),
    ("Market breadth", "/market/breadth"),
    ("Market regime", "/market/regime"),
    ("Backtest readiness", "/backtests/readiness"),
    ("Backtest history", "/backtests?limit=10"),
    ("Intelligence readiness", "/intelligence/readiness"),
    ("Latest intelligence", "/intelligence/events?limit=10"),
    ("Institutional readiness", "/institutional/readiness"),
    ("Institutional ranking", "/institutional?limit=10"),
    ("Sector strength", "/sector-strength"),
    ("Market-day operations", "/operations/readiness"),
    ("External scheduler", "/operations/external-scheduler/readiness"),
    ("Morning schedule contract", "/operations/external-scheduler/status?operation=morning"),
    ("EOD schedule contract", "/operations/external-scheduler/status?operation=eod"),
    ("Market-day session", "/operations/session"),
    ("Operations policy", "/operations/policy"),
    ("Operations control center", "/operations/control-center"),
    ("Operations runs", "/operations/runs?limit=10"),
    ("Notification readiness", "/notifications/readiness"),
    ("Notification producers", "/notifications/producers"),
    ("Notification policy", "/notifications/policy"),
    (
        "Notification daily summary",
        "/notifications/daily-summary/readiness",
    ),
    (
        "Notification daily preview",
        "/notifications/daily-summary/preview",
    ),
    ("Notification summary", "/notifications/summary"),
):
    with st.expander(title):
        try:
            st.json(client.get_json(path))
        except ApiError as exc:
            render_api_error(exc)
