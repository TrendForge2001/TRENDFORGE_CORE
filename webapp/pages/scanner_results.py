"""Dedicated, read-only R72.5 multi-strategy scanner results page."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import api_client
from webapp.ui import page_header, render_api_error


page_header(
    "Scanner Results",
    "Review the latest saved NIFTY 100 / 200 / 500 technical scan. "
    "BUY matches, all evaluated stocks, strategy coverage and failures are separated.",
    kicker="Technicals · Results",
)

client = api_client(timeout=70)
header_left, header_right = st.columns([4, 1])
with header_right:
    if st.button("Refresh results", use_container_width=True):
        st.rerun()

try:
    snapshot = client.get_json("/technical/multi-strategy/results", timeout=70)
except ApiError as exc:
    render_api_error(exc, title="Scanner result service unavailable")
    st.info("Opening this page does not start a scan. Return once Core is reachable.")
    st.stop()

scanner_state = str(snapshot.get("scanner_status") or "idle").upper()
progress = snapshot.get("progress")
progress = progress if isinstance(progress, dict) else {}
result = snapshot.get("last_result")
result = result if isinstance(result, dict) else {}
errors = result.get("errors") if isinstance(result.get("errors"), list) else []
strategies = (
    result.get("strategy_summary")
    if isinstance(result.get("strategy_summary"), list)
    else []
)
evaluated = result.get("results") if isinstance(result.get("results"), list) else []
candidates = (
    result.get("top_picks")
    if isinstance(result.get("top_picks"), list)
    else []
)

s1, s2, s3, s4 = st.columns(4)
with s1:
    st.metric("Scanner status", scanner_state)
with s2:
    st.metric("Evaluated", int(result.get("completed_symbols") or 0))
with s3:
    st.metric("BUY candidates", int(result.get("candidate_symbols") or 0))
with s4:
    st.metric("Errors", int(result.get("error_symbols") or 0))

if scanner_state == "RUNNING" or bool(progress.get("phase") in {
    "queued", "preparing", "fetching_kite_candles", "evaluating_strategies",
}):
    processed = int(progress.get("processed_symbols") or 0)
    total = int(progress.get("requested_symbols") or 0)
    st.info(
        f"Scanner is working: {progress.get('phase', 'running')} "
        f"· {processed}/{total} symbols. Results update after completion."
    )
    st.progress(min(1.0, max(0.0, float(progress.get("progress_pct") or 0) / 100)))

if snapshot.get("last_error"):
    st.error(f"Latest scan failed: {snapshot['last_error']}")

if not result:
    st.info(
        "No completed multi-strategy scan is available on this Render instance. "
        "This is not a zero-result trading signal. Run a scan manually from "
        "Technicals, then return here. Viewing this page never starts a scan."
    )
    st.page_link("pages/technicals.py", label="Open Technical Scanner", icon="📊")
    st.caption(
        "Historical results from an earlier Render instance may no longer be available "
        "because the current deployment uses ephemeral filesystem storage."
    )
    st.stop()

st.caption(
    f"Run ID: {result.get('run_id') or '—'}  |  "
    f"Universe: {result.get('universe') or '—'}  |  "
    f"Mode: {result.get('mode') or '—'}  |  "
    f"History: {result.get('period') or '—'} ({result.get('interval') or '—'})  |  "
    f"Completed: {result.get('completed_at_ist') or '—'}"
)
if snapshot.get("source") == "instance_snapshot":
    st.warning(
        "Showing a previously saved result from this instance, not a new scan. "
        "It may be lost when Render replaces its ephemeral instance."
    )
if int(result.get("candidate_symbols") or 0) == 0:
    if int(result.get("completed_symbols") or 0) > 0:
        st.info(
            "The scan evaluated symbols successfully, but no BUY/STRONG_BUY "
            "setups passed the defined strategy rules. See All evaluated stocks "
            "and Per-strategy summary below."
        )
    else:
        st.warning(
            "No symbols were successfully evaluated. Review the Errors tab "
            "and Kite/universe-provider readiness."
        )

buy_tab, all_tab, strategy_tab, errors_tab = st.tabs(
    ["BUY / Strong BUY", "All evaluated stocks", "Per-strategy summary", "Errors"]
)

def readable_rows(source_rows):
    rows = []
    for item in source_rows:
        if not isinstance(item, dict):
            continue
        risk = item.get("risk")
        risk = risk if isinstance(risk, dict) else {}
        rows.append({
            "Stock": item.get("symbol"),
            "Signal": item.get("consensus"),
            "Consensus score": item.get("consensus_score"),
            "Matched BUY strategies": item.get("buy_strategy_count"),
            "Notebook BUY": item.get("notebook_buy_count"),
            "Template BUY": item.get("template_buy_count"),
            "RSI confirmations": item.get("bullish_confirmation_count"),
            "Primary strategy": item.get("primary_strategy_id"),
            "Entry (₹)": risk.get("entry"),
            "Stop loss (₹)": risk.get("stoploss"),
            "Target (₹)": risk.get("target2"),
            "Candle at": item.get("bar_at"),
        })
    return rows

with buy_tab:
    if candidates:
        st.dataframe(
            pd.DataFrame(readable_rows(candidates)),
            use_container_width=True, hide_index=True,
        )
        selected = st.selectbox(
            "Inspect matched strategy conditions",
            [str(row.get("symbol")) for row in candidates],
            key="tf_scan_results_candidate",
        )
        match = next(
            (row for row in candidates if str(row.get("symbol")) == selected),
            None,
        )
        if match:
            st.markdown(f"**{selected} · {match.get('consensus', 'BUY')}**")
            evidence = match.get("strategy_evaluations")
            if isinstance(evidence, list) and evidence:
                st.dataframe(
                    pd.DataFrame(evidence),
                    use_container_width=True, hide_index=True,
                )
            st.json(match.get("risk") or {})
    else:
        st.info("No qualifying BUY candidates in the latest completed scan.")

with all_tab:
    if evaluated:
        filter_col, signal_col = st.columns([2, 1])
        with filter_col:
            search_text = st.text_input(
                "Filter by NSE symbol or strategy ID",
                key="tf_scan_result_filter",
            ).strip().lower()
        with signal_col:
            signal_filter = st.selectbox(
                "Signal",
                ["All", "STRONG_BUY", "BUY", "WATCH", "EXIT", "NEUTRAL"],
                key="tf_scan_result_signal",
            )
        filtered = [
            row for row in evaluated
            if isinstance(row, dict)
            and (
                not search_text
                or search_text in str(row.get("symbol") or "").lower()
                or search_text in " ".join(row.get("buy_strategy_ids") or []).lower()
            )
            and (
                signal_filter == "All" or row.get("consensus") == signal_filter
            )
        ]
        st.caption(
            f"{len(filtered)} of {len(evaluated)} successfully evaluated symbols"
        )
        if filtered:
            table = pd.DataFrame(readable_rows(filtered))
            st.dataframe(table, use_container_width=True, hide_index=True)
            st.download_button(
                "Export filtered results (CSV)",
                data=table.to_csv(index=False).encode("utf-8"),
                file_name="TrendForge_Multi_Strategy_Scanner_Results.csv",
                mime="text/csv",
            )
        else:
            st.info("No symbols match the selected filters.")
    else:
        st.warning("This scan has no successfully evaluated stock rows.")

with strategy_tab:
    if strategies:
        st.dataframe(
            pd.DataFrame([
                row for row in strategies if isinstance(row, dict)
            ]),
            use_container_width=True, hide_index=True,
        )
        st.caption(
            "Review-required strategies are not executable BUY signals. "
            "A zero BUY count can be valid when entry rules are not met."
        )
    else:
        st.info("No strategy-level results are available.")

with errors_tab:
    if errors:
        st.dataframe(
            pd.DataFrame(errors), use_container_width=True, hide_index=True,
        )
    else:
        st.success("No symbol-level errors reported for this run.")

with st.expander("Run metadata, provenance and safety", expanded=False):
    st.json({
        "run_id": result.get("run_id"),
        "started_at_ist": result.get("started_at_ist"),
        "completed_at_ist": result.get("completed_at_ist"),
        "universe_metadata": result.get("universe_metadata"),
        "provider_observation": result.get("provider_observation"),
        "snapshot_source": snapshot.get("source"),
        "snapshot_storage": snapshot.get("snapshot_storage"),
        "safety": result.get("safety"),
    })

st.download_button(
    "Download latest scan snapshot (JSON)",
    data=json.dumps(result, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
    file_name="TrendForge_Multi_Strategy_Last_Scan.json",
    mime="application/json",
    use_container_width=True,
)
st.caption(
    "Read-only dashboard. No scan, backtest, paper trade or broker order "
    "is started by visiting or refreshing this page."
)
