"""Persisted symbol-scoped news intelligence dashboard."""
from __future__ import annotations

from urllib.parse import quote

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "News Intelligence",
    "Inspect persisted symbol-level news evidence, source provenance, breaking-news flags, and transparent keyword-based impact scoring.",
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
    "News sentiment is a deterministic keyword heuristic, not AI sentiment analysis and not a trade signal."
)

r1, r2, r3 = st.columns(3)
with r1:
    st.metric(
        "Persisted news",
        int(readiness.get("persisted_news") or 0),
    )
with r2:
    st.metric(
        "Provider",
        str(readiness.get("news_provider") or "unknown"),
    )
with r3:
    st.metric(
        "Scoring",
        str(readiness.get("news_scoring") or "unknown"),
    )

with st.form("news_symbol_form"):
    a, b = st.columns([2, 1])
    with a:
        symbol = st.text_input(
            "Symbol",
            value=st.session_state.get(
                "tf_news_symbol",
                "TCS",
            ),
            max_chars=30,
        )
    with b:
        limit = st.selectbox(
            "Evidence rows",
            [20, 50, 100, 250],
            index=2,
        )

    submitted = st.form_submit_button(
        "Load news evidence",
        use_container_width=True,
    )

if submitted and symbol.strip():
    st.session_state["tf_news_symbol"] = (
        symbol.strip().upper()
    )

selected = str(
    st.session_state.get("tf_news_symbol", symbol)
).strip().upper()
encoded = quote(selected, safe="")

c1, c2 = st.columns(2)
with c1:
    refresh = st.button(
        f"Refresh {selected} news",
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
            else ["news"]
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
                        "days": 120,
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
    news = client.get_json(
        f"/intelligence/{encoded}/news",
        params={"limit": int(limit)},
    )
except ApiError as exc:
    render_api_error(
        exc,
        title="News evidence unavailable",
    )
    st.stop()

m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.metric("Articles", int(news.get("count") or 0))
with m2:
    st.metric("Positive", int(news.get("positive") or 0))
with m3:
    st.metric("Negative", int(news.get("negative") or 0))
with m4:
    st.metric("Neutral", int(news.get("neutral") or 0))
with m5:
    st.metric("Breaking", int(news.get("breaking") or 0))
with m6:
    st.metric(
        "Avg impact",
        f"{float(news.get('average_impact_score') or 0):.2f}",
    )

st.caption(
    f"Latest refresh: {news.get('latest_fetch_at') or 'not refreshed'} · "
    f"Combined news/corporate score: "
    f"{float(summary.get('combined_intelligence_score') or 0):.2f} "
    f"on {summary.get('score_range') or [-10, 10]}"
)

events = news.get("events")
events = events if isinstance(events, list) else []

st.subheader(f"{selected} news evidence")
if events:
    frame = pd.DataFrame(events)
    preferred = [
        "event_at",
        "event_type",
        "headline",
        "publisher",
        "source",
        "sentiment_label",
        "impact_score",
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
        "Download news evidence CSV",
        data=frame[columns].to_csv(index=False).encode("utf-8"),
        file_name=f"trendforge_{selected}_news.csv",
        mime="text/csv",
    )
else:
    st.info(
        "No persisted news evidence for this symbol. Use Refresh to query configured live providers."
    )

st.divider()
st.subheader("Latest persisted news across symbols")
try:
    latest = client.get_json(
        "/intelligence/events",
        params={
            "domain": "news",
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
                "sentiment_label",
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
        st.info("No persisted news events yet.")
except ApiError as exc:
    render_api_error(
        exc,
        title="Latest news evidence unavailable",
    )

with st.expander("Scoring methodology"):
    st.markdown(
        """
- Positive and negative words are matched deterministically against the headline.
- The impact score is bounded from -10 to +10.
- Breaking-news status is keyword-based.
- No LLM or AI sentiment classifier is used in R68.5.
- Source text remains the primary evidence; the heuristic score is only a triage aid.
"""
    )
