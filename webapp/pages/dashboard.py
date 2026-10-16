"""TrendForge command center."""
from __future__ import annotations

from typing import Any

import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import api_client
from webapp.ui import page_header, value_at


page_header(
    "Command Center",
    "A single operational view of API health, market-data readiness, scanner state, and paper-trading safety controls.",
    kicker="Operations",
)

if st.button("Refresh status", type="primary"):
    st.rerun()

client = api_client()


def safe_get(path: str) -> tuple[dict[str, Any] | None, ApiError | None]:
    try:
        return client.get_json(path), None
    except ApiError as exc:
        return None, exc


health, health_error = safe_get("/health")
paper, paper_error = safe_get("/paper/readiness")
auto, auto_error = safe_get("/paper/auto-entry/readiness")
scan_runtime, scan_error = safe_get("/observability/scan-runtime")

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Core API", str((health or {}).get("status", "unavailable")).upper())
with c2:
    st.metric(
        "NIFTY 500",
        str(
            value_at(
                health or {},
                "universe",
                "nifty500",
                "status",
                default="unknown",
            )
        ).upper(),
    )
with c3:
    st.metric(
        "Paper Trading",
        str((paper or {}).get("status", "unavailable")).upper(),
    )
with c4:
    active = value_at(scan_runtime or {}, "active", "run_id", default=None)
    st.metric("Scanner", "RUNNING" if active else "IDLE")

st.subheader("Execution safety")
e1, e2, e3 = st.columns(3)
with e1:
    st.metric(
        "Paper-only auto entry",
        "ON" if (auto or {}).get("enabled") else "OFF",
    )
with e2:
    st.metric(
        "Broker orders allowed",
        "YES" if (auto or {}).get("broker_orders_allowed") else "NO",
    )
with e3:
    monitor_status = value_at(
        paper or {},
        "automatic_monitor",
        "status",
        default="unknown",
    )
    st.metric("Quote monitor", str(monitor_status).upper())

st.subheader("Provider & deployment detail")
left, right = st.columns(2)
with left:
    st.markdown("**Core health**")
    if health is not None:
        st.json(health)
    elif health_error is not None:
        st.warning(str(health_error))
with right:
    st.markdown("**Paper runtime**")
    if paper is not None:
        st.json(paper)
    elif paper_error is not None:
        st.warning(str(paper_error))

with st.expander("Additional diagnostics"):
    if auto is not None:
        st.markdown("**Auto-entry readiness**")
        st.json(auto)
    elif auto_error is not None:
        st.warning(str(auto_error))

    if scan_runtime is not None:
        st.markdown("**Scan runtime**")
        st.json(scan_runtime)
    elif scan_error is not None:
        st.warning(str(scan_error))
