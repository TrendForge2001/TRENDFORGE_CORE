"""NIFTY 500 scanner control surface."""
from __future__ import annotations

from uuid import uuid4

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error, scan_rows


page_header(
    "NIFTY 500 Scanner",
    "Run bounded staged scans against the canonical R66/R67 pipeline. Results stay evidence-driven; paper auto-entry remains a separate explicit opt-in.",
    kicker="Scanner",
)

if not admin_key_configured():
    info_note(
        "Production scans require the TrendForge admin key. Configure it on the System page. Local development may run without production security.",
        danger=True,
    )

with st.form("scanner_controls"):
    a, b, c, d = st.columns(4)
    with a:
        limit = st.selectbox("Universe size", [25, 50, 100, 500], index=0)
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
        batch_size = st.selectbox("Batch size", [10, 25, 50, 100], index=1)

    e, f, g, h = st.columns(4)
    with e:
        period = st.selectbox("Lookback", ["3mo", "6mo", "1y"], index=1)
    with f:
        interval = st.selectbox("Interval", ["1d"], index=0)
    with g:
        compact = st.toggle("Compact response", value=True)
    with h:
        paper_auto_entry = st.toggle("Paper auto-entry", value=False)

    full_universe = limit == 500
    if paper_auto_entry:
        info_note(
            "Paper auto-entry is paper-only and still passes the R67.2 risk gate. It never authorizes real broker orders.",
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
            st.session_state["tf_last_scan"] = result
            st.session_state["tf_last_scan_run_id"] = run_id
        except ApiError as exc:
            render_api_error(exc, title="Scanner rejected the request")

result = st.session_state.get("tf_last_scan")
if isinstance(result, dict):
    st.divider()
    st.caption(
        f"Run ID: {st.session_state.get('tf_last_scan_run_id', 'unknown')}"
    )
    gate = (
        result.get("scale_gate")
        if isinstance(result.get("scale_gate"), dict)
        else {}
    )
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Outcome", str(result.get("outcome", "unknown")).upper())
    with m2:
        st.metric(
            "Completed",
            gate.get(
                "completed_symbols",
                result.get("completed_symbols", 0),
            ),
        )
    with m3:
        st.metric(
            "Errors",
            gate.get("error_symbols", result.get("error_symbols", 0)),
        )
    with m4:
        st.metric(
            "Missing",
            gate.get("missing_symbols", result.get("missing_symbols", 0)),
        )
    with m5:
        st.metric("Eligible", len(result.get("eligible") or []))

    rows = scan_rows(result)
    if rows:
        st.subheader("Ranked candidates")
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No ranked candidate rows were returned for this run.")

    auto = result.get("paper_auto_entry")
    if isinstance(auto, dict):
        st.subheader("Paper auto-entry report")
        st.json(auto)

    with st.expander("Scale gate & raw response"):
        if gate:
            st.markdown("**Scale gate**")
            st.json(gate)
        st.markdown("**Raw response**")
        st.json(result)
