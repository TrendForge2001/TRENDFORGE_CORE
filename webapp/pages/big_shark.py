"""Source-backed institutional / Big Shark dashboard."""
from __future__ import annotations

from urllib.parse import quote

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Big Shark Activity",
    "Inspect source-backed institutional ownership, shareholding changes, promoter evidence and bulk/block deal activity scored by the canonical Big Shark Engine.",
    kicker="Intelligence",
)

client = api_client(timeout=180)

try:
    readiness = client.get_json("/institutional/readiness")
except ApiError as exc:
    render_api_error(
        exc,
        title="Institutional service unavailable",
    )
    st.stop()

info_note(
    "Big Shark scoring is an evidence-confirmation layer, not a standalone trade signal. Missing institutional evidence lowers confidence instead of being treated as bullish."
)

r1, r2, r3, r4 = st.columns(4)
with r1:
    st.metric(
        "Engine",
        str(readiness.get("institutional_engine") or "unknown"),
    )
with r2:
    st.metric(
        "Provider",
        str(
            readiness.get("institutional_provider")
            or "unknown"
        ),
    )
with r3:
    st.metric(
        "Persisted symbols",
        int(
            readiness.get(
                "persisted_institutional_symbols"
            )
            or 0
        ),
    )
with r4:
    st.metric(
        "Trade signal",
        "YES" if readiness.get("trade_signal") else "NO",
    )

with st.form("institutional_symbol_form"):
    a, b = st.columns([1, 2])
    with a:
        symbol = st.text_input(
            "Inspect symbol",
            value=st.session_state.get(
                "tf_big_shark_symbol",
                "TCS",
            ),
            max_chars=30,
        )
    with b:
        refresh_symbols = st.text_input(
            "Refresh symbols (comma separated, max 25)",
            value=st.session_state.get(
                "tf_big_shark_refresh",
                "TCS",
            ),
        )

    submitted = st.form_submit_button(
        "Load symbol",
        use_container_width=True,
    )

if submitted and symbol.strip():
    st.session_state["tf_big_shark_symbol"] = (
        symbol.strip().upper()
    )

selected = str(
    st.session_state.get(
        "tf_big_shark_symbol",
        symbol,
    )
).strip().upper()
encoded = quote(selected, safe="")

refresh = st.button(
    "Refresh institutional evidence",
    type="primary",
    use_container_width=True,
)
if refresh:
    if not admin_key_configured():
        st.error(
            "Configure the production admin key before refreshing institutional evidence."
        )
    else:
        parsed = []
        seen = set()
        for raw in refresh_symbols.split(","):
            item = raw.strip().upper()
            if item and item not in seen:
                seen.add(item)
                parsed.append(item)
        if not parsed:
            st.error("Enter at least one symbol to refresh.")
        elif len(parsed) > 25:
            st.error("Refresh supports at most 25 symbols.")
        else:
            st.session_state["tf_big_shark_refresh"] = (
                ", ".join(parsed)
            )
            try:
                with st.spinner(
                    f"Refreshing {len(parsed)} institutional symbol(s)..."
                ):
                    result = client.post_json(
                        "/institutional/refresh",
                        {"symbols": parsed},
                        timeout=180,
                    )
                st.success(
                    "Institutional refresh complete · "
                    f"completed={result.get('completed_symbols', 0)} · "
                    f"failed={result.get('failed_symbols', 0)}"
                )
                if result.get("failures"):
                    st.warning(
                        "Some symbols failed; the last good persisted "
                        "snapshot is preserved for failed symbols."
                    )
                st.rerun()
            except ApiError as exc:
                render_api_error(
                    exc,
                    title="Institutional refresh failed",
                )

try:
    snapshot = client.get_json(
        f"/institutional/{encoded}"
    )
except ApiError as exc:
    render_api_error(
        exc,
        title="Institutional snapshot unavailable",
    )
    st.stop()

if snapshot.get("status") == "not_available":
    info_note(
        f"No persisted Big Shark snapshot exists for {selected}. Refresh the symbol first."
    )
else:
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        st.metric(
            "Score",
            f"{float(snapshot.get('score') or 0):.1f}",
        )
    with m2:
        st.metric(
            "Confidence",
            f"{float(snapshot.get('confidence') or 0):.1f}",
        )
    with m3:
        st.metric(
            "Grade",
            str(snapshot.get("grade") or "—"),
        )
    with m4:
        st.metric(
            "Bias",
            str(
                snapshot.get("institutional_bias")
                or "UNKNOWN"
            ),
        )
    with m5:
        st.metric(
            "Data quality",
            "YES" if snapshot.get("data_quality") else "NO",
        )
    with m6:
        st.metric(
            "Hard block",
            "YES" if snapshot.get("hard_block") else "NO",
        )

    st.caption(
        f"Snapshot: {snapshot.get('snapshot_updated_at') or 'unknown'} · "
        f"Methodology: {snapshot.get('methodology') or 'unknown'}"
    )

    ownership = snapshot.get("ownership")
    if isinstance(ownership, dict) and ownership:
        st.subheader("Institutional ownership")
        ownership_frame = pd.DataFrame(
            [
                {
                    "Category": key,
                    "Holding %": value,
                }
                for key, value in ownership.items()
            ]
        )
        st.dataframe(
            ownership_frame,
            use_container_width=True,
            hide_index=True,
        )

    changes = snapshot.get("holding_changes")
    changes = changes if isinstance(changes, dict) else {}
    change_rows = changes.get("rows")
    change_rows = (
        change_rows
        if isinstance(change_rows, list)
        else []
    )
    if change_rows:
        st.subheader("Shareholding changes")
        st.dataframe(
            pd.DataFrame(change_rows),
            use_container_width=True,
            hide_index=True,
        )

    deals = snapshot.get("deals")
    deals = deals if isinstance(deals, list) else []
    if deals:
        st.subheader("Bulk / block deal evidence")
        st.dataframe(
            pd.DataFrame(deals),
            use_container_width=True,
            hide_index=True,
        )

    p1, p2 = st.columns(2)
    with p1:
        st.subheader("Promoter evidence")
        st.json(snapshot.get("promoter") or {})
    with p2:
        st.subheader("Conviction")
        st.json(snapshot.get("conviction") or {})

    reasons = snapshot.get("reasons")
    reasons = reasons if isinstance(reasons, list) else []
    if reasons:
        st.subheader("Positive / confirming evidence")
        for item in reasons:
            st.markdown(f"- {item}")

    warnings = snapshot.get("warnings")
    warnings = warnings if isinstance(warnings, list) else []
    if warnings:
        st.subheader("Warnings")
        for item in warnings:
            st.warning(str(item))

    with st.expander("Provider provenance"):
        st.json(snapshot.get("provider_evidence") or {})

st.divider()
st.subheader("Persisted institutional ranking")
try:
    latest = client.get_json(
        "/institutional",
        params={"limit": 100},
    )
    rows = latest.get("snapshots")
    rows = rows if isinstance(rows, list) else []
    if rows:
        frame = pd.DataFrame(rows)
        st.dataframe(
            frame,
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "Download institutional ranking CSV",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name="trendforge_big_shark_ranking.csv",
            mime="text/csv",
        )
    else:
        st.info("No persisted institutional snapshots yet.")
except ApiError as exc:
    render_api_error(
        exc,
        title="Institutional ranking unavailable",
    )
