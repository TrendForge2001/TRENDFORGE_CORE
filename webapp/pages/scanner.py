"""NIFTY 500 scanner control surface with guarded continuation resume."""
from __future__ import annotations

from uuid import uuid4

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.scan_workflow import (
    continuation_from_result,
    continuation_is_resumable,
    scale_gate,
)
from webapp.ui import (
    info_note,
    page_header,
    render_api_error,
    scan_rows,
)


page_header(
    "NIFTY 500 Scanner",
    "Run bounded staged scans, review ranked evidence, and resume time-budgeted partial scans without changing their signal-defining inputs.",
    kicker="Scanner",
)

if not admin_key_configured():
    info_note(
        "Production scans require the TrendForge admin key. Configure it on the System page. Local development may run without production security.",
        danger=True,
    )


def store_scan_result(
    result: dict,
    run_id: str,
) -> None:
    st.session_state["tf_last_scan"] = result
    st.session_state["tf_last_scan_run_id"] = run_id
    continuation = continuation_from_result(result)
    if continuation is not None:
        st.session_state["tf_pending_continuation_token"] = (
            continuation["token"]
        )
    elif str(result.get("outcome") or "").lower() == "completed":
        st.session_state.pop(
            "tf_pending_continuation_token",
            None,
        )


with st.form("scanner_controls"):
    a, b, c, d = st.columns(4)
    with a:
        limit = st.selectbox(
            "Universe size",
            [25, 50, 100, 500],
            index=0,
        )
    with b:
        capital = st.number_input(
            "Capital (₹)",
            min_value=0.0,
            value=100000.0,
            step=10000.0,
        )
    with c:
        top_n = st.number_input(
            "Top picks",
            min_value=1,
            max_value=100,
            value=20,
            step=1,
        )
    with d:
        batch_size = st.selectbox(
            "Batch size",
            [10, 25, 50, 100],
            index=1,
        )

    e, f, g, h = st.columns(4)
    with e:
        period = st.selectbox(
            "Lookback",
            ["3mo", "6mo", "1y"],
            index=1,
        )
    with f:
        interval = st.selectbox(
            "Interval",
            ["1d"],
            index=0,
        )
    with g:
        compact = st.toggle(
            "Compact response",
            value=True,
        )
    with h:
        paper_auto_entry = st.toggle(
            "Paper auto-entry",
            value=False,
        )

    full_universe = limit == 500
    if paper_auto_entry:
        info_note(
            "Paper auto-entry is paper-only and still passes the R67.2 risk gate. Continuation children are never auto-entry eligible.",
            danger=True,
        )

    submitted = st.form_submit_button(
        "Run scanner",
        type="primary",
        use_container_width=True,
    )

if submitted:
    run_id = f"ui-{uuid4().hex[:16]}"
    payload = {
        "period": period,
        "interval": interval,
        "capital": float(capital),
        "top_n": int(top_n),
        "batch_size": int(batch_size),
        "batch_pause_seconds": 1.0,
        "scan_time_budget_seconds": 450.0,
        "batch_time_budget_seconds": 60.0,
        "limit": int(limit),
        "full_universe": bool(full_universe),
        "refresh_universe": False,
        "compact": bool(compact),
        "paper_auto_entry": bool(paper_auto_entry),
    }
    client = api_client(timeout=920)
    with st.spinner(f"Running scan {run_id}..."):
        try:
            result = client.post_json(
                "/scan/universe/nifty500",
                payload,
                params={"run_id": run_id},
                timeout=920,
            )
            store_scan_result(result, run_id)
        except ApiError as exc:
            render_api_error(
                exc,
                title="Scanner rejected the request",
            )

result = st.session_state.get("tf_last_scan")
if isinstance(result, dict):
    st.divider()
    run_id = st.session_state.get(
        "tf_last_scan_run_id",
        "unknown",
    )
    st.caption(f"Run ID: {run_id}")

    gate = scale_gate(result)
    completed = gate.get(
        "completed_symbols",
        result.get("completed_symbols", 0),
    )
    errors = gate.get(
        "error_symbols",
        result.get("error_symbols", 0),
    )
    missing = gate.get(
        "missing_symbols",
        result.get("missing_symbols", 0),
    )
    accounted_pct = gate.get(
        "accounted_pct",
        gate.get("completion_pct", 0.0),
    )
    budget_used = gate.get(
        "scan_budget_utilization_pct",
        0.0,
    )

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        st.metric(
            "Outcome",
            str(result.get("outcome", "unknown")).upper(),
        )
    with m2:
        st.metric("Completed", completed)
    with m3:
        st.metric("Errors", errors)
    with m4:
        st.metric("Missing", missing)
    with m5:
        st.metric(
            "Ranked",
            int(
                result.get(
                    "analysis_count",
                    len(result.get("analysis_ranked") or []),
                )
                or 0
            ),
        )
    with m6:
        st.metric(
            "Budget used",
            f"{float(budget_used or 0):.1f}%",
        )

    execution_eligible_count = int(
        result.get(
            "execution_count",
            len(result.get("eligible") or []),
        )
        or 0
    )
    st.caption(
        f"R67.3 dual gate · Execution eligible: "
        f"{execution_eligible_count} · Ranked analysis can remain available "
        "during corrections while execution stays fail-closed."
    )

    try:
        progress = max(
            0.0,
            min(1.0, float(accounted_pct or 0) / 100.0),
        )
        progress_label = float(accounted_pct or 0)
    except (TypeError, ValueError):
        progress = 0.0
        progress_label = 0.0
    st.progress(
        progress,
        text=f"Accounted progress: {progress_label:.1f}%",
    )

    rows = scan_rows(result)
    if rows:
        st.subheader("Ranked candidates")
        frame = pd.DataFrame(rows)
        signal_values = sorted(
            {
                str(value)
                for value in frame["Signal"].dropna().tolist()
            }
        )
        f1, f2 = st.columns([2, 1])
        with f1:
            selected_signals = st.multiselect(
                "Signal filter",
                signal_values,
                default=signal_values,
            )
        with f2:
            eligible_only = st.toggle(
                "Execution eligible only",
                value=False,
            )

        filtered = frame
        if selected_signals:
            filtered = filtered[
                filtered["Signal"].astype(str).isin(
                    selected_signals
                )
            ]
        if eligible_only:
            filtered = filtered[
                filtered["Execution Eligible"].fillna(False).astype(bool)
            ]

        st.dataframe(
            filtered,
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "Download ranked candidates CSV",
            data=filtered.to_csv(index=False).encode("utf-8"),
            file_name=f"trendforge_{run_id}_candidates.csv",
            mime="text/csv",
        )
    else:
        st.info(
            "No ranked candidate rows were returned for this run."
        )

    continuation = continuation_from_result(result)
    pending_token = st.session_state.get(
        "tf_pending_continuation_token"
    )
    if continuation is not None and pending_token:
        st.subheader("Resume deferred symbols")
        r1, r2, r3 = st.columns(3)
        with r1:
            st.metric(
                "Generation",
                continuation.get("generation", "—"),
            )
        with r2:
            st.metric(
                "Deferred",
                continuation.get("symbol_count", "—"),
            )
        with r3:
            st.metric(
                "Status",
                str(
                    continuation.get("status", "pending")
                ).upper(),
            )

        st.caption(
            "The continuation token remains in this browser session only. "
            "The backend intentionally does not copy the raw token into audit history."
        )

        inspect_client = api_client(timeout=30)
        continuation_state = continuation
        try:
            continuation_state = inspect_client.get_json(
                f"/observability/scan-continuations/{pending_token}"
            )
        except ApiError as exc:
            st.warning(
                "Continuation inspection is unavailable: "
                f"{exc}"
            )

        resumable = continuation_is_resumable(
            continuation_state
        )
        if not resumable:
            st.warning(
                "This continuation is no longer resumable."
            )

        if st.button(
            "Resume deferred symbols",
            type="primary",
            disabled=not resumable,
            use_container_width=True,
        ):
            child_run_id = (
                f"ui-resume-{uuid4().hex[:16]}"
            )
            resume_client = api_client(timeout=920)
            with st.spinner(
                f"Resuming as {child_run_id}..."
            ):
                try:
                    child = resume_client.post_json(
                        "/scan/universe/nifty500",
                        {},
                        params={
                            "run_id": child_run_id,
                            "continuation_token": pending_token,
                        },
                        timeout=920,
                    )
                    store_scan_result(
                        child,
                        child_run_id,
                    )
                    st.rerun()
                except ApiError as exc:
                    render_api_error(
                        exc,
                        title="Continuation resume failed",
                    )

        with st.expander("Continuation state"):
            st.json(continuation_state)

    auto = result.get("paper_auto_entry")
    if isinstance(auto, dict):
        st.subheader("Paper auto-entry report")
        st.json(auto)

    provider_counts = result.get("provider_counts")
    if not isinstance(provider_counts, dict):
        provider_counts = gate.get("provider_counts")
    if isinstance(provider_counts, dict) and provider_counts:
        st.subheader("Provider routing")
        provider_frame = pd.DataFrame(
            [
                {"Provider": key, "Count": value}
                for key, value in provider_counts.items()
            ]
        )
        st.dataframe(
            provider_frame,
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("Scale gate & raw response"):
        if gate:
            st.markdown("**Scale gate**")
            st.json(gate)
        st.markdown("**Raw response**")
        st.json(result)
