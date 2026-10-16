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
    summary = client.get_json("/notifications/summary")
except ApiError as exc:
    render_api_error(
        exc,
        title="Notification Center unavailable",
    )
    st.stop()

info_note(
    "R68.8 wires scanner, paper-trading, risk and system producers into the Discord-only Notification Center. Producer failures are best-effort and never alter scanner or paper-trading outcomes."
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

s1, s2, s3, s4, s5, s6 = st.columns(6)
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
