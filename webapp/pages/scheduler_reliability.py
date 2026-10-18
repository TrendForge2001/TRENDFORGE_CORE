"""Production scheduler reliability dashboard."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Scheduler Reliability",
    "Audit morning/EOD production operations, verify post-window completion, and surface missed or degraded runs.",
    kicker="Operations",
)

client = api_client(timeout=120)

days = st.segmented_control(
    "Reliability window",
    options=[7, 14, 30, 60, 90],
    default=30,
    format_func=lambda value: f"{value} days",
)

try:
    reliability = client.get_json(
        "/operations/reliability",
        params={"days": int(days or 30)},
    )
    history = client.get_json(
        "/operations/audit",
        params={"limit": 300},
    )
    scheduler = client.get_json(
        "/operations/external-scheduler/readiness"
    )
except ApiError as exc:
    render_api_error(
        exc,
        title="Scheduler reliability unavailable",
    )
    st.stop()

info_note(
    "R70.1 reliability is based on persisted external wake-up and post-window audit evidence. A missed, degraded, or unexpectedly disabled market-day operation is an operational failure; ordinary non-market days are not."
)

m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.metric(
        "Health",
        str(reliability.get("health") or "NO_DATA"),
    )
with m2:
    value = reliability.get("reliability_pct")
    st.metric(
        "Reliability",
        (
            f"{float(value):.2f}%"
            if value is not None
            else "—"
        ),
    )
with m3:
    st.metric(
        "Measured runs",
        int(reliability.get("measured_operations") or 0),
    )
with m4:
    st.metric(
        "Failures",
        int(reliability.get("failed_operations") or 0),
    )
with m5:
    delay = reliability.get(
        "average_completion_delay_minutes"
    )
    st.metric(
        "Avg completion delay",
        (
            f"{float(delay):.1f} min"
            if delay is not None
            else "—"
        ),
    )
with m6:
    st.metric(
        "External credential",
        str(scheduler.get("status") or "unknown").upper(),
    )

per_operation = reliability.get("per_operation")
per_operation = (
    per_operation
    if isinstance(per_operation, dict)
    else {}
)

st.subheader("Operation reliability")
operation_rows = []
for operation in ("morning", "eod"):
    item = per_operation.get(operation)
    item = item if isinstance(item, dict) else {}
    latest = item.get("latest")
    latest = latest if isinstance(latest, dict) else {}
    operation_rows.append(
        {
            "Operation": operation.upper(),
            "Reliability %": item.get("reliability_pct"),
            "Post-window audits": item.get("audit_checks", 0),
            "External wake ticks": item.get("external_ticks", 0),
            "Healthy": item.get("healthy", 0),
            "Missed": item.get("missed", 0),
            "Degraded": item.get("degraded", 0),
            "Config errors": item.get(
                "configuration_errors",
                0,
            ),
            "Not required": item.get("not_required", 0),
            "Avg delay min": item.get(
                "average_completion_delay_minutes"
            ),
            "Latest state": latest.get("audit_status"),
            "Latest reason": latest.get("reason"),
            "Latest audit": latest.get("recorded_at_ist"),
        }
    )

operation_frame = pd.DataFrame(operation_rows)
st.dataframe(
    operation_frame,
    use_container_width=True,
    hide_index=True,
)

st.subheader("Manual production audit")
a1, a2, a3 = st.columns(3)
with a1:
    operation = st.selectbox(
        "Operation",
        options=["all", "morning", "eod"],
    )
with a2:
    deliver_alerts = st.toggle(
        "Deliver alerts",
        value=False,
        help=(
            "When enabled, manual audit failures can route through "
            "the canonical Discord notification policy."
        ),
    )
with a3:
    st.caption(
        "Manual audit is admin protected and never executes a scanner or broker order."
    )

run_audit = st.button(
    "Run production audit",
    type="primary",
    use_container_width=True,
)

if run_audit:
    if not admin_key_configured():
        st.error(
            "Configure the production admin key before running a manual audit."
        )
    else:
        try:
            result = client.post_json(
                "/operations/audit/run",
                {
                    "operation": (
                        None
                        if operation == "all"
                        else operation
                    ),
                    "deliver_alerts": bool(deliver_alerts),
                },
                timeout=120,
            )
            state = str(result.get("status") or "unknown")
            if state in {
                "missed",
                "degraded",
                "configuration_error",
            }:
                st.error(f"Audit result: {state}")
            elif state == "degraded":
                st.warning(f"Audit result: {state}")
            else:
                st.success(f"Audit result: {state}")
            st.json(result)
        except ApiError as exc:
            render_api_error(
                exc,
                title="Manual production audit failed",
            )

st.subheader("Audit ledger")
events = history.get("events")
events = events if isinstance(events, list) else []
if not events:
    st.info(
        "No R70.1 reliability audit evidence has been recorded yet."
    )
else:
    rows = []
    for event in events:
        if not isinstance(event, dict):
            continue
        alert = event.get("alert")
        alert = alert if isinstance(alert, dict) else {}
        rows.append(
            {
                "Recorded IST": event.get("recorded_at_ist"),
                "Date": event.get("date_ist"),
                "Event": event.get("event_type"),
                "Operation": event.get("operation"),
                "State": event.get("audit_status"),
                "Reason": event.get("reason"),
                "Trigger": event.get("trigger_source"),
                "Contract": event.get("contract_status"),
                "Tick": event.get("tick_status"),
                "Delay min": event.get(
                    "completion_delay_minutes"
                ),
                "Alert": alert.get("status"),
                "Alert event": alert.get("event_id"),
                "Audit ID": event.get("audit_id"),
            }
        )

    frame = pd.DataFrame(rows)
    state_filter = st.multiselect(
        "Audit state",
        options=sorted(
            {
                str(value)
                for value in frame["State"].dropna().tolist()
            }
        ),
        default=[],
    )
    if state_filter:
        frame = frame[
            frame["State"].astype(str).isin(state_filter)
        ]

    st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Download reliability audit CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name="trendforge_scheduler_reliability.csv",
        mime="text/csv",
    )

with st.expander("Reliability semantics"):
    st.markdown(
        """
- **Healthy**: the expected morning/EOD operation has a completed run.
- **Missed**: its execution window elapsed without a completed/degraded run.
- **Degraded**: the operation ran but one or more required steps failed.
- **Configuration error**: external production scheduling is active but the expected operation or automation policy is unexpectedly disabled.
- **Not required**: a normal weekend/configured holiday where no operation is expected.
- External wake-up attempts and post-window audits are stored separately, so redundant scheduler calls do not inflate the reliability percentage.
- Missed/degraded/configuration alerts are deduplicated by operation, date, and state.
- Alert delivery remains a side channel: it cannot change scanner signals, paper positions, or broker permissions.
"""
    )
