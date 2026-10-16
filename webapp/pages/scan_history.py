"""Immutable scan audit, lineage and continuation diagnostics."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import api_client
from webapp.scan_workflow import (
    continuation_is_resumable,
    lineage_run_rows,
    scan_history_rows,
)
from webapp.ui import page_header, render_api_error


page_header(
    "Scan History",
    "Inspect immutable NIFTY 500 scan audits, continuation lineages, end-to-end completion, and integrity findings.",
    kicker="Observability",
)

client = api_client(timeout=60)
limit = st.selectbox(
    "Recent audit rows",
    [20, 50, 100, 250, 500],
    index=1,
)

try:
    history = client.get_json(
        "/observability/scan-runs",
        params={"limit": int(limit)},
    )
except ApiError as exc:
    render_api_error(
        exc,
        title="Scan history unavailable",
    )
    st.stop()

rows = scan_history_rows(history)
if not rows:
    st.info("No scan audit records are available.")
    st.stop()

frame = pd.DataFrame(rows)
st.dataframe(
    frame,
    use_container_width=True,
    hide_index=True,
)
st.download_button(
    "Download audit history CSV",
    data=frame.to_csv(index=False).encode("utf-8"),
    file_name="trendforge_scan_audit_history.csv",
    mime="text/csv",
)

run_ids = [
    str(row["Run ID"])
    for row in rows
    if row.get("Run ID")
]
selected_run = st.selectbox(
    "Inspect run",
    run_ids,
    index=0,
)

detail = lineage = integrity = None
try:
    detail = client.get_json(
        f"/observability/scan-runs/{selected_run}"
    )
except ApiError as exc:
    render_api_error(exc, title="Run detail unavailable")

try:
    lineage = client.get_json(
        f"/observability/scan-lineages/{selected_run}"
    )
except ApiError as exc:
    st.warning(f"Lineage unavailable: {exc}")

try:
    integrity = client.get_json(
        f"/observability/scan-lineages/{selected_run}/integrity"
    )
except ApiError as exc:
    st.warning(f"Integrity report unavailable: {exc}")

if isinstance(lineage, dict):
    st.subheader("Lineage rollup")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric(
            "Status",
            str(lineage.get("status", "unknown")).upper(),
        )
    with c2:
        st.metric(
            "Root requested",
            lineage.get("root_requested_symbols", 0),
        )
    with c3:
        st.metric(
            "Completed",
            lineage.get(
                "cumulative_completed_symbols",
                0,
            ),
        )
    with c4:
        st.metric(
            "Remaining",
            lineage.get("remaining_symbols", 0),
        )
    with c5:
        st.metric(
            "End-to-end",
            f"{float(lineage.get('end_to_end_completion_pct') or 0):.1f}%",
        )

    lineage_rows = lineage_run_rows(lineage)
    if lineage_rows:
        st.dataframe(
            pd.DataFrame(lineage_rows),
            use_container_width=True,
            hide_index=True,
        )

if isinstance(integrity, dict):
    report = integrity.get("integrity")
    if isinstance(report, dict):
        st.subheader("Lineage integrity")
        i1, i2, i3 = st.columns(3)
        with i1:
            st.metric(
                "Integrity",
                str(
                    report.get("status", "unknown")
                ).upper(),
            )
        with i2:
            st.metric(
                "Errors",
                report.get("error_count", 0),
            )
        with i3:
            st.metric(
                "Warnings",
                report.get("warning_count", 0),
            )
        issues = report.get("issues")
        if isinstance(issues, list) and issues:
            st.dataframe(
                pd.DataFrame(issues),
                use_container_width=True,
                hide_index=True,
            )

with st.expander("Selected audit record"):
    if isinstance(detail, dict):
        st.json(detail)

with st.expander("Raw lineage rollup"):
    if isinstance(lineage, dict):
        st.json(lineage)

st.divider()
st.subheader("Continuation token inspector")
st.caption(
    "Raw continuation tokens are deliberately absent from immutable audit history. "
    "Paste a token retained from a partial scan response to inspect its current state."
)
token = st.text_input(
    "Continuation token",
    type="password",
    key="history_continuation_token",
).strip()

if st.button(
    "Inspect token",
    disabled=not bool(token),
):
    try:
        st.session_state["tf_history_continuation"] = (
            client.get_json(
                f"/observability/scan-continuations/{token}"
            )
        )
        st.session_state[
            "tf_history_continuation_raw_token"
        ] = token
    except ApiError as exc:
        render_api_error(
            exc,
            title="Continuation inspection failed",
        )

continuation = st.session_state.get(
    "tf_history_continuation"
)
if isinstance(continuation, dict):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(
            "Status",
            str(
                continuation.get(
                    "effective_status",
                    continuation.get("status", "unknown"),
                )
            ).upper(),
        )
    with c2:
        st.metric(
            "Generation",
            continuation.get("generation", "—"),
        )
    with c3:
        st.metric(
            "Attempts left",
            continuation.get(
                "claim_attempts_remaining",
                "—",
            ),
        )
    st.json(continuation)

    if continuation_is_resumable(continuation):
        st.info(
            "This token is still resumable. Use the NIFTY 500 Scanner page "
            "from the same browser session when the token came from the latest "
            "partial scan response."
        )
