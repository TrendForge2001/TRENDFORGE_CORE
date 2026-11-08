"""Batch history, progress and backend-generated research reports."""

import base64
import hashlib
import math

import pandas as pd
import streamlit as st

from core.deployment_role import cloud_read_only
from scanner.strategy_horizons import HORIZONS
from services.execution_report import TRADE_COLUMNS
from webapp.api_client import ApiError
from webapp.market_colours import market_frame
from webapp.paper_excel import (
    paper_daily_xlsx,
    strategy_paper_xlsx,
    validate_daily_statement,
)
from webapp.trade_timestamps import format_trade_frame
from webapp.ui import render_api_error


def render_completed_report(batch, client=None):
    report = batch.get("report")
    if not isinstance(report, dict) or not isinstance(report.get("rows"), list):
        raise ApiError("The completed batch has no generated report")
    content = report.get("csv")
    if not isinstance(content, str) or hashlib.sha256(
        content.encode("utf-8-sig")
    ).hexdigest() != report.get("sha256"):
        raise ApiError("Generated report checksum does not match")
    workbook = None
    if report.get("xlsx_base64"):
        workbook = base64.b64decode(report["xlsx_base64"], validate=True)
        if hashlib.sha256(workbook).hexdigest() != report.get("xlsx_sha256"):
            raise ApiError("Generated Excel checksum does not match")
    st.caption("Download this completed batch report")
    csv_button, excel_button = st.columns(2)
    csv_button.download_button(
        "Download CSV",
        content.encode("utf-8-sig"),
        report["filename"],
        "text/csv",
        key="report_csv_" + batch["batch_id"],
        width="stretch",
        type="primary",
    )
    if workbook is not None:
        excel_button.download_button(
            "Download Excel (.xlsx)",
            workbook,
            report["filename"].removesuffix(".csv") + ".xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="report_excel_" + batch["batch_id"],
            width="stretch",
        )
    frame = pd.DataFrame(report["rows"])
    if batch["kind"] == "backtest":
        if report.get("report_type") != "historical_backtest_exit_fills":
            raise ApiError("This batch is not a historical trade report")
        st.subheader("Trade entries and exits")
        if frame.empty:
            st.info("The backtest completed with no historical trades.")
        else:
            st.caption(
                "Each row is an actual exit fill. Partial and final exits share "
                "the same trade number."
            )
            shown = frame[TRADE_COLUMNS].copy()
            for column in ("entry_at", "exit_at"):
                shown[column] = pd.to_datetime(shown[column], utc=True).dt.tz_convert(
                    "Asia/Kolkata"
                )
            st.dataframe(
                market_frame(shown),
                hide_index=True,
                width="stretch",
                column_config={
                    "entry_at": st.column_config.DatetimeColumn(
                        "Entry (IST)", timezone="Asia/Kolkata"
                    ),
                    "exit_at": st.column_config.DatetimeColumn(
                        "Exit (IST)", timezone="Asia/Kolkata"
                    ),
                    "entry_price": st.column_config.NumberColumn(
                        "Entry price", format="₹%.2f"
                    ),
                    "exit_price": st.column_config.NumberColumn(
                        "Exit price", format="₹%.2f"
                    ),
                    "transaction_costs": st.column_config.NumberColumn(
                        "Costs", format="₹%.2f"
                    ),
                    "net_pnl": st.column_config.NumberColumn("Net P&L", format="₹%.2f"),
                },
            )
            st.caption(
                "Daily candles identify the bar date; exact intrabar fill times "
                "are not available."
            )
    else:
        if report.get("report_type") != "scanner_indicator_snapshot":
            raise ApiError("This batch is not a scanner report")
        st.subheader("Scanner report")
        st.caption(
            "These are candidate signals and planned levels, not executed trades."
        )
        visible = [
            column
            for column in (
                "symbol",
                "signal",
                "score",
                "entry",
                "stoploss",
                "partial_target",
                "entry_state",
                "execution_blocked_reason",
            )
            if column in frame
        ]
        st.dataframe(market_frame(frame[visible]), hide_index=True, width="stretch")
        with st.expander("Indicator evidence"):
            st.dataframe(market_frame(frame), hide_index=True, width="stretch")
    if batch["kind"] == "scan" and client is not None and not cloud_read_only():
        from webapp.paper_handoff import render_scanner_paper_handoff

        with st.expander("Use candidates for supervised paper automation"):
            render_scanner_paper_handoff(
                client,
                {
                    "strategy_id": report["strategy_id"],
                    "results": report["rows"],
                    "scanner_options": report.get("scanner_options", {}),
                },
            )
    with st.expander("Run details"):
        st.json(
            {
                key: report.get(key)
                for key in (
                    "run_id",
                    "horizon",
                    "strategy_id",
                    "stock_list",
                    "mode",
                    "period",
                    "generated_at",
                    "registry_version",
                    "engine",
                    "parameters",
                    "metrics",
                    "history_alignment",
                    "scanner_counts",
                    "sha256",
                )
            }
        )


@st.fragment(run_every=5)
def render_batches(client):
    try:
        offset = st.session_state.setdefault("tf_report_offset", 0)
        response = client.get_json(
            "/reports/batches", params={"limit": 100, "offset": offset}, timeout=15
        )
        rows = response.get("batches")
        if not isinstance(rows, list) or not all(
            isinstance(row, dict) and isinstance(row.get("batch_id"), str)
            for row in rows
        ):
            raise ApiError("Invalid research batch history")
        newer, older = st.columns(2)
        if newer.button("Newer batches", disabled=offset == 0):
            st.session_state["tf_report_offset"] = max(0, offset - 100)
            st.session_state.pop("tf_report_selected_batch", None)
            st.rerun()
        if older.button("Older batches", disabled=len(rows) < 100):
            st.session_state["tf_report_offset"] = offset + 100
            st.session_state.pop("tf_report_selected_batch", None)
            st.rerun()
        if not rows:
            st.info(
                "No recorded batches on this page. Start a scan or historical backtest."
            )
            return
        display = pd.DataFrame(rows)
        display["horizon"] = display["horizon"].map(
            lambda value: HORIZONS.get(value, "Historical selection")
        )
        display["progress"] = display.apply(
            lambda row: f"{row['completed_symbols']}/{row['requested_symbols']}", axis=1
        )
        columns = [
            "created_at",
            "kind",
            "horizon",
            "strategy_id",
            "stock_list",
            "status",
            "phase",
            "progress",
        ]
        ids = [row["batch_id"] for row in rows]
        widget_key = (
            "batch_history_" + hashlib.sha256("|".join(ids).encode()).hexdigest()[:12]
        )
        st.caption(
            "Select a batch to open its report. Running batches refresh every "
            "five seconds."
        )
        selection = st.dataframe(
            format_trade_frame(display[columns]),
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=widget_key,
        )
        indices = selection.selection.rows
        if indices and 0 <= indices[0] < len(ids):
            st.session_state["tf_report_selected_batch"] = ids[indices[0]]
        batch_id = st.session_state.setdefault("tf_report_selected_batch", ids[0])
        cache = st.session_state.setdefault("tf_completed_reports", {})
        batch = cache.get(batch_id)
        if batch is None:
            batch = client.get_json("/reports/batches/" + batch_id, timeout=20)
            if batch.get("status") == "completed":
                cache[batch_id] = batch
                if len(cache) > 5:
                    cache.pop(next(iter(cache)))
        st.caption("Batch: " + batch_id)
        if batch.get("status") in {"queued", "running"}:
            total = max(1, int(batch["requested_symbols"]))
            value = min(1.0, max(0.0, batch["completed_symbols"] / total))
            st.progress(value, text=str(batch["phase"]).replace("_", " ").title())
            st.info(
                "The backend is working. The detailed report will appear "
                "automatically when complete."
            )
        elif batch.get("status") == "completed":
            render_completed_report(batch, client)
        else:
            st.warning(
                "Batch "
                + str(batch.get("status"))
                + ": "
                + str(batch.get("error_code") or "unavailable")
            )
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ApiError):
            render_api_error(exc, title="Reports unavailable")
        else:
            st.error("Report data is incomplete; no totals or downloads are displayed.")


def render_paper_reports(client):
    st.subheader("Paper statements")
    try:
        portfolio = client.get_json("/workspace/paper-portfolio")["portfolio"]
        if (
            not isinstance(portfolio, dict)
            or type(portfolio.get("open_positions")) is not int
            or not isinstance(portfolio.get("positions"), list)
            or portfolio["open_positions"] != len(portfolio["positions"])
            or any(
                type(portfolio.get(key)) not in {int, float}
                or not math.isfinite(portfolio[key])
                for key in ("unrealized_pnl", "realized_pnl")
            )
        ):
            raise ValueError("Incomplete paper portfolio")
        statement = client.get_json("/pnl", params={"period": "daily"})
        validate_daily_statement(statement, portfolio)
        left, right = st.columns(2)
        left.metric("Daily realized P&L", f"₹{statement['summary']['net_pnl']:,.2f}")
        right.metric("Closed trades", statement["summary"]["trade_count"])
        st.caption(
            "Daily closed paper trades. Open marks are not fresh-quote evidence."
        )
        st.dataframe(
            market_frame(format_trade_frame(pd.DataFrame(statement.get("trades", [])))),
            hide_index=True,
            width="stretch",
        )
        st.download_button(
            "Download daily paper statement",
            paper_daily_xlsx(statement, portfolio),
            "trendforge_paper_daily.xlsx",
        )
    except (ApiError, ValueError, KeyError, TypeError):
        st.info("A complete daily paper statement is unavailable on this runtime.")
    with st.expander("Results by saved strategy"):
        try:
            period = (
                st.segmented_control(
                    "Statement period",
                    ["daily", "weekly", "monthly", "yearly", "all"],
                    default="all",
                    selection_mode="single",
                )
                or "all"
            )
            statement = client.get_json(
                "/paper/strategy-pnl", params={"period": period}
            )
            workbook = strategy_paper_xlsx(statement)
            closed = [
                {**trade, "strategy_id": row["strategy_id"]}
                for row in statement["rows"]
                for trade in row["closed_trades"]
            ]
            st.dataframe(
                market_frame(format_trade_frame(pd.DataFrame(closed))),
                hide_index=True,
                width="stretch",
            )
            st.download_button(
                "Download all paper strategies",
                workbook,
                f"trendforge_paper_{period}_strategies.xlsx",
            )
        except (ApiError, ValueError, KeyError, TypeError):
            st.info("Complete strategy statements are unavailable on this runtime.")
