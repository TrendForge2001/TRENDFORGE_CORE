"""Discord-only notification routing and delivery dashboard."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Notification Center",
    "Route, inspect and audit TrendForge events through the canonical Discord-only notification boundary.",
    kicker="Monitor",
)

client = api_client(timeout=60)

try:
    readiness = client.get_json("/notifications/readiness")
    producers = client.get_json("/notifications/producers")
    policy_state = client.get_json("/notifications/policy")
    daily_runtime = client.get_json(
        "/notifications/daily-summary/readiness"
    )
    daily_preview = client.get_json(
        "/notifications/daily-summary/preview"
    )
    summary = client.get_json("/notifications/summary")
except ApiError as exc:
    render_api_error(
        exc,
        title="Notification Center unavailable",
    )
    st.stop()

info_note(
    "R68.9 adds policy-controlled Discord routing and an optional 18:30 IST daily digest. Filtered events remain persisted evidence. Notification failures remain best-effort and never alter scanner or paper-trading outcomes."
)

r1, r2, r3, r4, r5 = st.columns(5)
discord = readiness.get("discord")
discord = discord if isinstance(discord, dict) else {}
with r1:
    st.metric(
        "Discord",
        "READY" if discord.get("enabled") else "NOT READY",
    )
with r2:
    st.metric(
        "Configured",
        "YES" if discord.get("configured") else "NO",
    )
with r3:
    st.metric(
        "Persisted events",
        int(readiness.get("persisted_events") or 0),
    )
with r4:
    st.metric(
        "Cooldown",
        f"{int(readiness.get('cooldown_minutes') or 0)} min",
    )
with r5:
    st.metric(
        "Channel",
        str(readiness.get("channel") or "discord").upper(),
    )

p1, p2, p3, p4 = st.columns(4)
with p1:
    st.metric(
        "Producer status",
        str(producers.get("status") or "unknown").upper(),
    )
with p2:
    st.metric(
        "Producer attempts",
        int(producers.get("attempted") or 0),
    )
with p3:
    st.metric(
        "Producer failures",
        int(producers.get("failures") or 0),
    )
with p4:
    st.metric(
        "Scanner pick cap",
        int(producers.get("max_scan_picks") or 0),
    )

if producers.get("last_error"):
    st.warning(
        f"Latest producer error: {producers.get('last_error')}"
    )

st.divider()
st.subheader("Alert policy & routing preferences")

policy = policy_state.get("policy")
policy = policy if isinstance(policy, dict) else {}
policy_categories = policy.get("categories")
policy_categories = (
    policy_categories
    if isinstance(policy_categories, dict)
    else {}
)
quiet = policy.get("quiet_hours")
quiet = quiet if isinstance(quiet, dict) else {}
daily_policy = policy.get("daily_summary")
daily_policy = (
    daily_policy
    if isinstance(daily_policy, dict)
    else {}
)

with st.form("notification_policy_form"):
    delivery_enabled = st.toggle(
        "Discord delivery enabled",
        value=bool(policy.get("delivery_enabled", True)),
    )

    st.caption(
        "Minimum severity is evaluated only for delivered events. "
        "Record-only evidence is still persisted."
    )
    severity_options = [
        "INFO",
        "SUCCESS",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ]
    category_payload = {}
    for category_name in categories:
        existing = policy_categories.get(category_name)
        existing = (
            existing
            if isinstance(existing, dict)
            else {}
        )
        left, right = st.columns(2)
        with left:
            enabled_value = st.toggle(
                f"{category_name.title()} alerts",
                value=bool(existing.get("enabled", True)),
                key=f"policy_enabled_{category_name}",
            )
        with right:
            current_severity = str(
                existing.get("minimum_severity") or "INFO"
            ).upper()
            severity_index = (
                severity_options.index(current_severity)
                if current_severity in severity_options
                else 0
            )
            minimum_severity = st.selectbox(
                f"{category_name.title()} minimum severity",
                severity_options,
                index=severity_index,
                key=f"policy_severity_{category_name}",
            )
        category_payload[category_name] = {
            "enabled": enabled_value,
            "minimum_severity": minimum_severity,
        }

    q1, q2, q3, q4 = st.columns(4)
    with q1:
        quiet_enabled = st.toggle(
            "Quiet hours",
            value=bool(quiet.get("enabled", False)),
        )
    with q2:
        quiet_start = st.text_input(
            "Quiet start IST",
            value=str(quiet.get("start") or "22:00"),
            max_chars=5,
        )
    with q3:
        quiet_end = st.text_input(
            "Quiet end IST",
            value=str(quiet.get("end") or "07:00"),
            max_chars=5,
        )
    with q4:
        quiet_critical = st.toggle(
            "Allow CRITICAL in quiet hours",
            value=bool(quiet.get("allow_critical", True)),
        )

    d1, d2, d3, d4 = st.columns(4)
    with d1:
        digest_enabled = st.toggle(
            "Daily Discord summary",
            value=bool(daily_policy.get("enabled", False)),
        )
    with d2:
        digest_time = st.text_input(
            "Summary time IST",
            value=str(daily_policy.get("time_ist") or "18:30"),
            max_chars=5,
        )
    with d3:
        digest_skip_empty = st.toggle(
            "Skip empty summary",
            value=bool(daily_policy.get("skip_empty", True)),
        )
    with d4:
        digest_notable = st.number_input(
            "Notable events",
            min_value=1,
            max_value=25,
            value=int(daily_policy.get("notable_limit") or 10),
            step=1,
        )

    save_policy = st.form_submit_button(
        "Save alert policy",
        type="primary",
        use_container_width=True,
    )

if save_policy:
    if not admin_key_configured():
        st.error(
            "Configure the production admin key before changing alert policy."
        )
    else:
        try:
            client.put_json(
                "/notifications/policy",
                {
                    "delivery_enabled": delivery_enabled,
                    "categories": category_payload,
                    "quiet_hours": {
                        "enabled": quiet_enabled,
                        "start": quiet_start.strip(),
                        "end": quiet_end.strip(),
                        "allow_critical": quiet_critical,
                    },
                    "daily_summary": {
                        "enabled": digest_enabled,
                        "time_ist": digest_time.strip(),
                        "skip_empty": digest_skip_empty,
                        "notable_limit": int(digest_notable),
                    },
                },
                timeout=30,
            )
            st.success("Alert policy updated.")
            st.rerun()
        except ApiError as exc:
            render_api_error(
                exc,
                title="Alert policy update failed",
            )

with st.expander("Daily Discord summary"):
    ds1, ds2, ds3, ds4 = st.columns(4)
    with ds1:
        st.metric(
            "Worker",
            str(daily_runtime.get("status") or "unknown").upper(),
        )
    with ds2:
        st.metric(
            "Scheduled",
            str(
                daily_runtime.get("scheduled_time_ist")
                or daily_policy.get("time_ist")
                or "18:30"
            ),
        )
    with ds3:
        st.metric(
            "Today's events",
            int(daily_preview.get("event_count") or 0),
        )
    with ds4:
        st.metric(
            "Delivery issues",
            int(daily_preview.get("delivery_issues") or 0),
        )

    st.json(
        {
            "date": daily_preview.get("date"),
            "statuses": daily_preview.get("statuses"),
            "categories": daily_preview.get("categories"),
            "scanner_picks": daily_preview.get("scanner_picks"),
            "paper_opened": daily_preview.get("paper_opened"),
            "paper_closed": daily_preview.get("paper_closed"),
            "risk_events": daily_preview.get("risk_events"),
            "notable_events": daily_preview.get("notable_events"),
        }
    )

    send_col, reset_col = st.columns(2)
    with send_col:
        if st.button(
            "Send today's Discord summary",
            use_container_width=True,
        ):
            if not admin_key_configured():
                st.error(
                    "Configure the production admin key before sending the summary."
                )
            else:
                try:
                    result = client.post_json(
                        "/notifications/daily-summary/send",
                        {
                            "summary_date": None,
                            "force": False,
                        },
                        timeout=30,
                    )
                    status = str(
                        result.get("status") or "unknown"
                    )
                    if status == "sent":
                        st.success("Daily summary delivered.")
                    elif status in {
                        "already_sent",
                        "skipped_empty",
                        "disabled",
                    }:
                        st.info(
                            f"Daily summary status: {status}"
                        )
                    else:
                        st.warning(
                            f"Daily summary status: {status}"
                        )
                    st.rerun()
                except ApiError as exc:
                    render_api_error(
                        exc,
                        title="Daily summary send failed",
                    )
    with reset_col:
        if st.button(
            "Reset alert policy to defaults",
            use_container_width=True,
        ):
            if not admin_key_configured():
                st.error(
                    "Configure the production admin key before resetting policy."
                )
            else:
                try:
                    client.delete_json(
                        "/notifications/policy",
                        timeout=30,
                    )
                    st.success(
                        "Alert policy reset to built-in defaults."
                    )
                    st.rerun()
                except ApiError as exc:
                    render_api_error(
                        exc,
                        title="Alert policy reset failed",
                    )

st.divider()

if st.button(
    "Send Discord test",
    type="primary",
    use_container_width=True,
):
    if not admin_key_configured():
        st.error(
            "Configure the production admin key before sending a Discord test."
        )
    else:
        try:
            result = client.post_json(
                "/notifications/test",
                {},
                timeout=30,
            )
            status = str(result.get("status") or "unknown")
            if status == "sent":
                st.success(
                    "Discord test event was delivered and persisted."
                )
            elif status == "blocked":
                st.warning(
                    "Test event was persisted but Discord delivery is blocked."
                )
            else:
                st.error(
                    f"Discord test finished with status: {status}"
                )
            st.rerun()
        except ApiError as exc:
            render_api_error(
                exc,
                title="Discord test failed",
            )

st.divider()
st.subheader("Route event")

categories = readiness.get("categories")
categories = (
    categories
    if isinstance(categories, list) and categories
    else [
        "scanner",
        "paper",
        "risk",
        "system",
        "intelligence",
        "market",
        "portfolio",
    ]
)
severities = readiness.get("severities")
severities = (
    severities
    if isinstance(severities, list) and severities
    else ["INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
)

with st.form("notification_event_form"):
    a, b, c = st.columns(3)
    with a:
        category = st.selectbox(
            "Category",
            categories,
            index=0,
        )
    with b:
        severity = st.selectbox(
            "Severity",
            severities,
            index=0,
        )
    with c:
        symbol = st.text_input(
            "Symbol (optional)",
            max_chars=30,
        )

    event_type = st.text_input(
        "Event type",
        value="manual_event",
        max_chars=80,
    )
    title = st.text_input(
        "Title",
        value="TrendForge Alert",
        max_chars=256,
    )
    message = st.text_area(
        "Message",
        max_chars=4000,
        height=120,
    )

    d1, d2 = st.columns(2)
    with d1:
        deliver = st.toggle(
            "Deliver to Discord",
            value=True,
        )
    with d2:
        dedupe_key = st.text_input(
            "Dedupe key (optional)",
            max_chars=200,
            help=(
                "Identical routed events are automatically deduplicated. "
                "Supply a stable key when upstream systems already have one."
            ),
        )

    routed = st.form_submit_button(
        "Route event",
        use_container_width=True,
    )

if routed:
    if not admin_key_configured():
        st.error(
            "Configure the production admin key before routing events."
        )
    elif not message.strip():
        st.error("Message is required.")
    else:
        payload = {
            "event_type": event_type.strip(),
            "category": str(category),
            "severity": str(severity),
            "title": title.strip(),
            "message": message.strip(),
            "symbol": symbol.strip().upper() or None,
            "source": "notification_center_webapp",
            "payload": {
                "origin": "webapp",
            },
            "dedupe_key": dedupe_key.strip() or None,
            "deliver": bool(deliver),
        }
        try:
            result = client.post_json(
                "/notifications/events",
                payload,
                timeout=30,
            )
            status = str(result.get("status") or "unknown")
            if status == "sent":
                st.success("Event delivered to Discord.")
            elif status == "recorded":
                st.success(
                    "Event recorded without Discord delivery."
                )
            elif status == "suppressed":
                st.warning(
                    "Duplicate event suppressed by the cooldown window."
                )
            elif status == "blocked":
                st.warning(
                    f"Event persisted but delivery blocked: "
                    f"{result.get('error') or 'unknown reason'}"
                )
            else:
                st.error(
                    f"Event routing finished with status: {status}"
                )
            st.rerun()
        except ApiError as exc:
            render_api_error(
                exc,
                title="Event routing failed",
            )

st.divider()
st.subheader("Delivery summary")

s1, s2, s3, s4, s5, s6, s7 = st.columns(7)
with s1:
    st.metric("Total", int(summary.get("total") or 0))
with s2:
    st.metric("Sent", int(summary.get("sent") or 0))
with s3:
    st.metric("Recorded", int(summary.get("recorded") or 0))
with s4:
    st.metric("Suppressed", int(summary.get("suppressed") or 0))
with s5:
    st.metric("Blocked", int(summary.get("blocked") or 0))
with s6:
    st.metric("Filtered", int(summary.get("filtered") or 0))
with s7:
    st.metric("Failed", int(summary.get("failed") or 0))

category_counts = summary.get("categories")
if isinstance(category_counts, dict) and category_counts:
    category_frame = pd.DataFrame(
        [
            {"Category": key, "Events": value}
            for key, value in category_counts.items()
        ]
    ).set_index("Category")
    st.bar_chart(category_frame)

st.subheader("Event history")

f1, f2, f3, f4 = st.columns(4)
with f1:
    filter_category = st.selectbox(
        "Filter category",
        ["All", *categories],
    )
with f2:
    filter_status = st.selectbox(
        "Filter status",
        [
            "All",
            "sent",
            "recorded",
            "suppressed",
            "filtered",
            "blocked",
            "failed",
        ],
    )
with f3:
    filter_symbol = st.text_input(
        "Filter symbol",
        key="notification_filter_symbol",
        max_chars=30,
    )
with f4:
    limit = st.selectbox(
        "Rows",
        [20, 50, 100, 250, 500],
        index=2,
    )

params = {
    "limit": int(limit),
}
if filter_category != "All":
    params["category"] = filter_category
if filter_status != "All":
    params["status"] = filter_status
if filter_symbol.strip():
    params["symbol"] = filter_symbol.strip().upper()

try:
    history = client.get_json(
        "/notifications/events",
        params=params,
    )
except ApiError as exc:
    render_api_error(
        exc,
        title="Notification history unavailable",
    )
    st.stop()

events = history.get("events")
events = events if isinstance(events, list) else []

if events:
    frame = pd.DataFrame(events)
    preferred = [
        "created_at",
        "event_id",
        "category",
        "event_type",
        "severity",
        "symbol",
        "title",
        "source",
        "channel",
        "status",
        "sent_at",
        "error",
    ]
    columns = [
        column
        for column in preferred
        if column in frame.columns
    ]
    st.dataframe(
        frame[columns],
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Download notification history CSV",
        data=frame[columns].to_csv(index=False).encode("utf-8"),
        file_name="trendforge_notification_events.csv",
        mime="text/csv",
    )

    event_ids = [
        str(row.get("event_id"))
        for row in events
        if row.get("event_id")
    ]
    if event_ids:
        selected_event = st.selectbox(
            "Inspect event",
            event_ids,
        )
        selected_row = next(
            (
                row
                for row in events
                if str(row.get("event_id")) == selected_event
            ),
            {},
        )
        with st.expander(
            f"Event detail · {selected_event}",
            expanded=False,
        ):
            st.json(selected_row)
else:
    st.info("No notification events match the current filters.")

with st.expander("Routing semantics"):
    st.markdown(
        """
- Scanner, paper-trading, risk and startup/system producers feed this canonical route automatically.
- Policy-filtered delivery attempts are persisted with status **filtered** and do not call Discord.
- Quiet hours use Asia/Kolkata and can optionally allow CRITICAL alerts through.
- The optional daily summary is generated from canonical notification evidence and defaults to 18:30 IST when enabled.
- Producer routing is best-effort: notification failures never change scanner or paper-trading outcomes.
- Completed scans deliver at most the configured execution-pick cap; partial scans only record their summary.
- All canonical routes terminate at **Discord** only.
- deliver=false records evidence without network delivery.
- Duplicate sent/recorded events are suppressed during the configured cooldown window.
- Failed or blocked deliveries can be retried because they do not poison the dedupe window.
- A missing webhook produces a persisted blocked event instead of silently pretending delivery succeeded.
- The Discord webhook URL is never returned by readiness, history, or dashboard APIs.
"""
    )
