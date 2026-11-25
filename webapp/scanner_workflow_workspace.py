"""Compact scanner history and strategy-only backtesting results."""

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.downloads import download_link
from webapp.ui import render_api_error


@st.fragment(run_every=15)
def scanner_reports(client):
    try:
        payload = client.get_json("/reports/scanner-runs", timeout=30)
        if not isinstance(payload, dict) or not isinstance(payload.get("runs"), list):
            raise ApiError("The backend returned incomplete scanner history")
        runs = payload["runs"]
        st.caption(
            "Latest 10 completed scanner runs. Each run contains all "
            "BUY/SELL/WAIT stocks; older scanner reports are removed "
            "automatically."
        )
        if not runs:
            st.info(
                "Run Stock Scanner to create a report. Paper trading has its "
                "own readiness and statements."
            )
            return
        choices = {row["run_id"]: row for row in runs}
        selected = st.selectbox(
            "Scanner run",
            list(choices),
            format_func=lambda key: (
                f"{choices[key]['stock_list']} · {choices[key]['created_at'][:19]}"
            ),
            key="tf_workflow_report_run",
        )
        report = client.get_json("/reports/scanner-runs/" + selected, timeout=30)
        rows = report["rows"]
        query = st.text_input("Find stock or strategy", key="tf_workflow_report_search")
        filtered = [
            row
            for row in rows
            if query.upper().strip()
            in (
                str(row.get("symbol", "")) + " " + str(row.get("strategy_id", ""))
            ).upper()
        ]
        frame = pd.DataFrame(filtered)
        columns = [
            key
            for key in (
                "symbol",
                "strategy_name",
                "horizon",
                "signal",
                "entry",
                "stoploss",
                "target2",
                "stock_rating",
                "rating_score",
                "data_status",
                "data_reason",
            )
            if key in frame
        ]
        st.dataframe(frame[columns], hide_index=True, width="stretch")
        st.caption(
            "Detailed stock research is available under Stock Scanner → "
            "Stock report. Backtesting contains the queued BUY/SELL/EXIT "
            "stocks."
        )
    except ApiError as exc:
        render_api_error(exc, title="Scanner reports unavailable")


@st.fragment(run_every=15)
def scanner_backtests(client, *, authorized):
    try:
        snapshot = client.get_json("/reports/backtest-queue", timeout=30)
        if (
            not isinstance(snapshot, dict)
            or not isinstance(snapshot.get("strategies"), list)
            or not isinstance(snapshot.get("jobs"), list)
            or not isinstance(snapshot.get("pending_stocks"), int)
        ):
            raise ApiError("The backend returned incomplete backtest queue status")
        st.caption(
            "Historical research on scanner-selected stocks. Paper "
            "readiness runs independently; profitability does not "
            "activate trading."
        )
        if st.button(
            "Backtest queued stocks",
            type="primary",
            disabled=not authorized or not snapshot["pending_stocks"],
            key="tf_workflow_backtest_start",
        ):
            client.post_json("/reports/backtest-queue/start", {}, timeout=20)
            st.success(
                "Queued strategies will run sequentially. Paper automation "
                "settings are unchanged."
            )
        rows = snapshot["strategies"]
        if not rows:
            st.info(
                "BUY/SELL/EXIT signals from Stock Scanner will appear here "
                "with their strategy."
            )
            return
        if snapshot["pending_stocks"] and st.button(
            "Export queued stock strategies", key="tf_workflow_queue_export"
        ):
            content = client.get_bytes(
                "/reports/backtest-queue/queued-stocks.xlsx", timeout=60
            )
            st.session_state["tf_workflow_queue_export_bytes"] = (
                snapshot.get("queue_fingerprint"),
                content,
            )
        saved_queue = st.session_state.get("tf_workflow_queue_export_bytes")
        if (
            snapshot["pending_stocks"]
            and saved_queue
            and saved_queue[0] == snapshot.get("queue_fingerprint")
        ):
            download_link(
                "Download protected queue",
                saved_queue[1],
                "trendforge-queued-stock-strategies.xlsx",
            )
        st.dataframe(
            pd.DataFrame(
                [
                    {"Strategy": row["strategy"], "Profitability": row["profitability"]}
                    for row in rows
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        jobs = {
            row["job_id"]: row
            for row in snapshot["jobs"]
            if row["status"] == "completed"
        }
        if jobs:
            from scanner.strategy_registry import get_strategy

            choice = st.selectbox(
                "Excel evidence",
                list(jobs),
                format_func=lambda key: (
                    get_strategy(jobs[key]["strategy_id"])["name"]
                    + " · "
                    + jobs[key]["created_at"][:19]
                ),
                key="tf_workflow_export_job",
            )
            from webapp.evidence_panel import strategy_evidence

            strategy_evidence(
                {
                    "strategy_provenance": jobs[choice].get("strategy_provenance")
                    or {
                        "strategy_id": jobs[choice]["strategy_id"],
                        "registry_version": "unrecorded",
                        "policy_version": "unrecorded",
                    }
                }
            )
            if st.button("Prepare encrypted Excel", key="tf_workflow_export"):
                content = client.get_bytes(
                    "/reports/backtest-queue/" + choice + "/trades.xlsx", timeout=120
                )
                st.session_state["tf_workflow_encrypted_export"] = (choice, content)
            saved = st.session_state.get("tf_workflow_encrypted_export")
            if saved and saved[0] == choice:
                download_link(
                    "Download protected trade details",
                    saved[1],
                    "trendforge-backtest-trades.xlsx",
                )
                st.caption(
                    "Open with your TrendForge password. The workbook includes "
                    "stock/strategy provenance and every original trade-evidence "
                    "sheet."
                )
    except ApiError as exc:
        render_api_error(exc, title="Backtesting queue unavailable")
