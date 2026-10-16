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
institutional, institutional_error = safe_get(
    "/institutional/readiness"
)
sector_strength, sector_strength_error = safe_get(
    "/sector-strength"
)
notifications, notifications_error = safe_get(
    "/notifications/readiness"
)
notification_summary, notification_summary_error = safe_get(
    "/notifications/summary"
)
notification_producers, notification_producers_error = safe_get(
    "/notifications/producers"
)
notification_policy, notification_policy_error = safe_get(
    "/notifications/policy"
)
daily_summary_runtime, daily_summary_runtime_error = safe_get(
    "/notifications/daily-summary/readiness"
)
operations, operations_error = safe_get(
    "/operations/readiness"
)
operations_session, operations_session_error = safe_get(
    "/operations/session"
)
external_scheduler, external_scheduler_error = safe_get(
    "/operations/external-scheduler/readiness"
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

st.subheader("Institutional & sector confirmation")
is1, is2, is3, is4 = st.columns(4)
with is1:
    st.metric(
        "Big Shark symbols",
        int(
            (institutional or {}).get(
                "persisted_institutional_symbols"
            )
            or 0
        ),
    )
with is2:
    sectors = (
        (sector_strength or {}).get("sectors")
        if isinstance(sector_strength, dict)
        else []
    )
    sectors = sectors if isinstance(sectors, list) else []
    top_sector = sectors[0] if sectors else {}
    st.metric(
        "Top sector",
        str(top_sector.get("sector") or "—"),
    )
with is3:
    st.metric(
        "Top sector score",
        (
            f"{float(top_sector.get('score')):.1f}"
            if top_sector.get("score") is not None
            else "—"
        ),
    )
with is4:
    st.metric(
        "Sector coverage",
        (
            f"{float((sector_strength or {}).get('coverage_pct')):.1f}%"
            if (sector_strength or {}).get("coverage_pct") is not None
            else "—"
        ),
    )

st.subheader("Alerts & routing")
n1, n2, n3, n4, n5, n6 = st.columns(6)
notification_discord = (
    (notifications or {}).get("discord")
    if isinstance(notifications, dict)
    else {}
)
notification_discord = (
    notification_discord
    if isinstance(notification_discord, dict)
    else {}
)
with n1:
    st.metric(
        "Discord",
        "READY"
        if notification_discord.get("enabled")
        else "NOT READY",
    )
with n2:
    st.metric(
        "Sent",
        int((notification_summary or {}).get("sent") or 0),
    )
with n3:
    delivery_issues = (
        int((notification_summary or {}).get("failed") or 0)
        + int((notification_summary or {}).get("blocked") or 0)
    )
    st.metric("Delivery issues", delivery_issues)
with n4:
    st.metric(
        "Suppressed",
        int(
            (notification_summary or {}).get("suppressed")
            or 0
        ),
    )
with n5:
    st.metric(
        "Producer errors",
        int(
            (notification_producers or {}).get("failures")
            or 0
        ),
    )
with n6:
    policy_payload = (
        (notification_policy or {}).get("policy")
        if isinstance(notification_policy, dict)
        else {}
    )
    policy_payload = (
        policy_payload
        if isinstance(policy_payload, dict)
        else {}
    )
    daily_payload = policy_payload.get("daily_summary")
    daily_payload = (
        daily_payload
        if isinstance(daily_payload, dict)
        else {}
    )
    st.metric(
        "Daily summary",
        (
            str(
                daily_summary_runtime.get(
                    "scheduled_time_ist",
                    daily_payload.get("time_ist", "18:30"),
                )
            )
            if daily_payload.get("enabled")
            else "OFF"
        ),
    )

st.subheader("Scheduled operations")
o1, o2, o3, o4, o5 = st.columns(5)
with o1:
    st.metric(
        "Market phase",
        str(
            (operations_session or {}).get(
                "phase",
                "unknown",
            )
        ).upper(),
    )
with o2:
    st.metric(
        "Market day",
        (
            "YES"
            if (operations_session or {}).get(
                "market_day"
            )
            else "NO"
        ),
    )
with o3:
    st.metric(
        "Automation",
        (
            "ON"
            if (operations or {}).get(
                "automation_enabled"
            )
            else "OFF"
        ),
    )
with o4:
    st.metric(
        "Operations worker",
        str(
            (operations or {}).get(
                "status",
                "unknown",
            )
        ).upper(),
    )
with o5:
    st.metric(
        "External wake-up",
        str(
            (external_scheduler or {}).get(
                "status",
                "unknown",
            )
        ).upper(),
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

    if institutional is not None:
        st.markdown("**Institutional readiness**")
        st.json(institutional)
    elif institutional_error is not None:
        st.warning(str(institutional_error))

    if sector_strength is not None:
        st.markdown("**Sector-strength snapshot**")
        st.json(sector_strength)
    elif sector_strength_error is not None:
        st.warning(str(sector_strength_error))

    if notifications is not None:
        st.markdown("**Notification readiness**")
        st.json(notifications)
    elif notifications_error is not None:
        st.warning(str(notifications_error))

    if notification_summary is not None:
        st.markdown("**Notification summary**")
        st.json(notification_summary)
    elif notification_summary_error is not None:
        st.warning(str(notification_summary_error))

    if notification_producers is not None:
        st.markdown("**Notification producers**")
        st.json(notification_producers)
    elif notification_producers_error is not None:
        st.warning(str(notification_producers_error))

    if notification_policy is not None:
        st.markdown("**Notification policy**")
        st.json(notification_policy)
    elif notification_policy_error is not None:
        st.warning(str(notification_policy_error))

    if daily_summary_runtime is not None:
        st.markdown("**Daily summary runtime**")
        st.json(daily_summary_runtime)
    elif daily_summary_runtime_error is not None:
        st.warning(str(daily_summary_runtime_error))

    if operations is not None:
        st.markdown("**Scheduled operations**")
        st.json(operations)
    elif operations_error is not None:
        st.warning(str(operations_error))

    if operations_session is not None:
        st.markdown("**Market-day session**")
        st.json(operations_session)
    elif operations_session_error is not None:
        st.warning(str(operations_session_error))

    if external_scheduler is not None:
        st.markdown("**External scheduler**")
        st.json(external_scheduler)
    elif external_scheduler_error is not None:
        st.warning(str(external_scheduler_error))
