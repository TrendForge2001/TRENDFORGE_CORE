"""Persisted corporate-action intelligence dashboard."""
from __future__ import annotations

from urllib.parse import quote

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Corporate Actions",
    "Inspect persisted NSE corporate-action evidence, event type, timing, impact weights, high-impact flags, and upcoming events.",
    kicker="Intelligence",
)

client = api_client(timeout=120)

try:
    readiness = client.get_json("/intelligence/readiness")
except ApiError as exc:
    render_api_error(
        exc,
        title="Intelligence service unavailable",
    )
    st.stop()

info_note(
    "Corporate-action impact is a deterministic event-weight heuristic. It is context for scanner/research workflows, not a standalone buy/sell signal."
)

r1, r2, r3 = st.columns(3)
with r1:
    st.metric(
        "Persisted actions",
        int(
            readiness.get(
                "persisted_corporate_actions"
            )
            or 0
        ),
    )
with r2:
    st.metric(
        "Provider",
        str(
            readiness.get(
                "corporate_action_provider"
            )
            or "unknown"
        ),
    )
with r3:
    st.metric(
        "Scoring",
        str(
            readiness.get(
                "corporate_action_scoring"
            )
            or "unknown"
        ),
    )

with st.form("corporate_action_symbol_form"):
    a, b, c = st.columns([2, 1, 1])
    with a:
        symbol = st.text_input(
            "Symbol",
            value=st.session_state.get(
                "tf_corporate_symbol",
                "TCS",
            ),
            max_chars=30,
        )
    with b:
        days = st.selectbox(
            "Lookback days",
            [30, 60, 90, 120, 180, 365],
            index=3,
        )
    with c:
        limit = st.selectbox(
            "Evidence rows",
            [20, 50, 100, 250],
            index=2,
        )

    submitted = st.form_submit_button(
        "Load corporate actions",
        use_container_width=True,
    )

if submitted and symbol.strip():
    st.session_state["tf_corporate_symbol"] = (
        symbol.strip().upper()
    )

selected = str(
    st.session_state.get(
        "tf_corporate_symbol",
        symbol,
    )
).strip().upper()
encoded = quote(selected, safe="")

c1, c2 = st.columns(2)
with c1:
    refresh = st.button(
        f"Refresh {selected} corporate actions",
        type="primary",
        use_container_width=True,
    )
with c2:
    refresh_both = st.button(
        f"Refresh all intelligence for {selected}",
        use_container_width=True,
    )

if refresh or refresh_both:
    if not admin_key_configured():
        st.error(
            "Configure the production admin key before refreshing live intelligence."
        )
    else:
        domains = (
            ["news", "corporate_actions"]
            if refresh_both
            else ["corporate_actions"]
        )
        try:
            with st.spinner(
                f"Refreshing intelligence for {selected}..."
            ):
                result = client.post_json(
                    "/intelligence/refresh",
                    {
                        "symbols": [selected],
                        "domains": domains,
                        "days": int(days),
                    },
                    timeout=120,
                )
            st.success(
                "Refresh completed · "
                f"news={result.get('news_events', 0)} · "
                f"corporate actions={result.get('corporate_action_events', 0)}"
            )
            st.rerun()
        except ApiError as exc:
            render_api_error(
                exc,
                title="Intelligence refresh failed",
            )

try:
    summary = client.get_json(
        f"/intelligence/{encoded}/summary"
    )
    actions = client.get_json(
        f"/intelligence/{encoded}/corporate-actions",
        params={"limit": int(limit)},
    )
except ApiError as exc:
    render_api_error(
        exc,
        title="Corporate-action evidence unavailable",
    )
    st.stop()

m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.metric("Events", int(actions.get("count") or 0))
with m2:
    st.metric(
        "Positive",
        int(actions.get("positive_impact") or 0),
    )
with m3:
    st.metric(
        "Negative",
        int(actions.get("negative_impact") or 0),
    )
with m4:
    st.metric(
        "High impact",
        int(actions.get("high_impact") or 0),
    )
with m5:
    st.metric(
        "Upcoming",
        int(actions.get("upcoming") or 0),
    )
with m6:
    st.metric(
        "Avg impact",
        f"{float(actions.get('average_impact_score') or 0):.2f}",
    )

st.caption(
    f"Next event: {actions.get('next_event_at') or 'none in persisted evidence'} · "
    f"Latest refresh: {actions.get('latest_fetch_at') or 'not refreshed'} · "
    f"Combined intelligence score: "
    f"{float(summary.get('combined_intelligence_score') or 0):.2f}"
)

events = actions.get("events")
events = events if isinstance(events, list) else []

st.subheader(f"{selected} corporate-action evidence")
if events:
    frame = pd.DataFrame(events)
    preferred = [
        "event_at",
        "event_type",
        "headline",
        "summary",
        "impact_score",
        "source",
        "url",
        "fetched_at",
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
        "Download corporate actions CSV",
        data=frame[columns].to_csv(index=False).encode("utf-8"),
        file_name=(
            f"trendforge_{selected}_corporate_actions.csv"
        ),
        mime="text/csv",
    )
else:
    st.info(
        "No persisted corporate-action evidence for this symbol. Use Refresh to query the configured NSE provider."
    )

st.divider()
st.subheader("Latest persisted corporate actions")
try:
    latest = client.get_json(
        "/intelligence/events",
        params={
            "domain": "corporate_action",
            "limit": 100,
        },
    )
    latest_rows = latest.get("events")
    latest_rows = (
        latest_rows
        if isinstance(latest_rows, list)
        else []
    )
    if latest_rows:
        latest_frame = pd.DataFrame(latest_rows)
        latest_columns = [
            column
            for column in (
                "symbol",
                "event_at",
                "event_type",
                "headline",
                "impact_score",
                "source",
            )
            if column in latest_frame.columns
        ]
        st.dataframe(
            latest_frame[latest_columns],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No persisted corporate-action events yet.")
except ApiError as exc:
    render_api_error(
        exc,
        title="Latest corporate-action evidence unavailable",
    )

with st.expander("Event-weight methodology"):
    st.markdown(
        """
Examples of configured weights include buyback +9, bonus +8, merger +8, split +7, dividend +5, penalty -6, default -8, and insolvency/delisting -10. Multiple matched terms can contribute before the score is bounded to -10..+10.

The original source fields remain available in each persisted details object even when the dashboard shows a normalized event type.
"""
    )
