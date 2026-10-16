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
breadth, breadth_error = safe_get("/market/breadth")
regime, regime_error = safe_get("/market/regime")
intelligence, intelligence_error = safe_get(
    "/intelligence/readiness"
)

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

st.subheader("Market context")
mc1, mc2, mc3, mc4 = st.columns(4)
with mc1:
    st.metric(
        "Regime",
        str((regime or {}).get("regime", "not available")).upper(),
    )
with mc2:
    st.metric(
        "Breadth",
        str((breadth or {}).get("direction", "not available")).upper(),
    )
with mc3:
    coverage = (breadth or {}).get("coverage_pct")
    st.metric(
        "Breadth coverage",
        (
            f"{float(coverage):.1f}%"
            if coverage is not None
            else "—"
        ),
    )
with mc4:
    st.metric(
        "Breadth score",
        (
            f"{float((breadth or {}).get('breadth_score')):.1f}"
            if (breadth or {}).get("breadth_score") is not None
            else "—"
        ),
    )

st.subheader("Intelligence evidence")
i1, i2, i3 = st.columns(3)
with i1:
    st.metric(
        "News evidence",
        int((intelligence or {}).get("persisted_news") or 0),
    )
with i2:
    st.metric(
        "Corporate actions",
        int(
            (intelligence or {}).get(
                "persisted_corporate_actions"
            )
            or 0
        ),
    )
with i3:
    st.metric(
        "AI sentiment",
        "ON"
        if (intelligence or {}).get("ai_sentiment")
        else "OFF",
    )

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

    if breadth is not None:
        st.markdown("**Market breadth snapshot**")
        st.json(breadth)
    elif breadth_error is not None:
        st.warning(str(breadth_error))

    if regime is not None:
        st.markdown("**Market regime snapshot**")
        st.json(regime)
    elif regime_error is not None:
        st.warning(str(regime_error))

    if intelligence is not None:
        st.markdown("**Intelligence readiness**")
        st.json(intelligence)
    elif intelligence_error is not None:
        st.warning(str(intelligence_error))
