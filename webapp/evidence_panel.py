"""Consistent, expandable evidence beneath compact trading summaries."""

from contextlib import nullcontext

import pandas as pd
import streamlit as st

from services.evaluation_diagnostics import diagnostics
from services.paper_trade_audit import audit
from services.strategy_provenance import identity


def strategy_evidence(record, *, expanded=False, inline=False):
    saved = record.get("strategy_provenance")
    saved = saved if isinstance(saved, dict) else identity(record)
    with (
        nullcontext()
        if inline
        else st.expander("Strategy version & provenance", expanded=expanded)
    ):
        for key, value in saved.items():
            st.caption(key.replace("_", " ").title() + ": " + str(value))
        st.caption(
            "Unrecorded means historical evidence did not retain that "
            "version. It is never replaced with today's version."
        )


def evaluation_evidence(rows, *, key):
    if not rows:
        return
    with st.expander("Evaluation health & reasons"):
        options = {str(i): row for i, row in enumerate(rows)}
        selected = st.selectbox(
            "Inspect evaluation",
            list(options),
            format_func=lambda i: str(options[i].get("symbol") or "Unknown stock"),
            key=key,
        )
        row = options[selected]
        st.dataframe(pd.DataFrame(diagnostics(row)), hide_index=True, width="stretch")
        st.caption(
            "Technical signals, data availability and institutional "
            "coverage are separate. An unavailable component never "
            "supplies a fabricated score or trade."
        )
        strategy_evidence(row, inline=True)


def trade_evidence(row):
    evidence = row.get("audit") or audit(row)
    status = evidence["status"]
    st.caption(
        "Fill arithmetic: " + str(evidence.get("accounting_status") or "unrecorded")
    )
    if status == "VERIFIED":
        st.success("Saved fill arithmetic reconciles with its recorded cost model.")
    elif status in {"MISMATCH", "INVALID_EVIDENCE"}:
        st.error(
            "Saved trade evidence does not reconcile. The ledger has not been altered."
        )
    else:
        st.warning(
            "Historical evidence is incomplete; full reconciliation cannot be claimed."
        )
    st.write(evidence["exit_explanation"])
    st.caption("Exit code: " + str(evidence.get("exit_code") or "unrecorded"))
    details = [
        {
            "Evidence": key.replace("_", " ").title(),
            "Recorded / calculated": str(evidence.get(key))
            if evidence.get(key) is not None
            else "unavailable",
        }
        for key in (
            "closed_at",
            "exit_signal_at",
            "stop_basis",
            "raw_entry_price",
            "entry_fill",
            "raw_exit_price",
            "exit_fill",
            "slippage_bps",
            "quantity",
            "computed_gross_pnl",
            "recorded_charges",
            "delivery_charge",
            "computed_net_pnl",
            "recorded_net_pnl",
            "adverse_distance_from_stop",
        )
    ]
    st.dataframe(pd.DataFrame(details), hide_index=True, width="stretch")
    st.caption(evidence["formula"])
    if evidence.get("stop_note"):
        st.caption(evidence["stop_note"])
    for label, values in (
        ("Missing evidence", evidence["missing"]),
        ("Failed checks", evidence["failures"]),
    ):
        if values:
            st.write(label + ": " + ", ".join(values))
    strategy_evidence({"strategy_provenance": evidence["strategy"]}, inline=True)


def recovery_evidence(readiness):
    restore = readiness.get("position_restore") or {}
    monitor = readiness.get("automatic_monitor") or {}
    storage = readiness.get("entry_storage_policy") or {}
    with st.expander("Restart recovery & monitoring"):
        st.write("Position recovery: " + str(restore.get("status") or "unavailable"))
        st.write(
            "Restored positions at startup: "
            + str(restore.get("open_trades", "unavailable"))
        )
        st.write(
            "Currently tracked positions: "
            + str(readiness.get("open_positions", "unavailable"))
        )
        running = monitor.get("enabled") is True and monitor.get("running") is True
        st.write(
            "Quote exit monitor: "
            + ("running" if running else "stopped or unavailable")
        )
        st.caption(
            "Last successful monitor poll: "
            + str(monitor.get("last_success_at") or "not recorded")
        )
        st.caption(
            "Storage / entry policy: "
            + str(
                storage.get("message")
                or storage.get("reason")
                or storage.get("mode")
                or "unavailable"
            )
        )
        st.caption(
            "Recovery does not activate new entries. Restored entry marks"
            " are not fresh quotes. Existing-position exits remain "
            "available independently of entry automation, subject to "
            "monitor and data readiness."
        )
