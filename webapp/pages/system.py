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
    "Inspect the server-managed API connection and production diagnostics.",
    kicker="Administration",
)

st.caption("API authentication is saved on the server; no API key is required here.")
col1, col2 = st.columns(2)
with col1:
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

with col2:
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
    "The operator manages the API URL and API authentication through server environment settings. Sign in using only the webapp access key."
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
    (
        "Strategy-driven paper readiness",
        "/paper/strategy-driven/readiness",
    ),
    (
        "Strategy paper monitor",
        "/paper/strategy-monitor/readiness",
    ),
    (
        "Strategy paper performance",
        "/paper/strategy-performance",
    ),
    (
        "Strategy runtime reconciliation",
        "/paper/strategy-runtime/reconciliation",
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
    ("Scheduler reliability", "/operations/reliability?days=30"),
    ("Operations audit ledger", "/operations/audit?limit=20"),
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
