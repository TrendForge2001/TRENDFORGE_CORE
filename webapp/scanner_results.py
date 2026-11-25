"""One compact stock view; technical and institutional evidence stay distinct."""

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.market_colours import market_frame
from webapp.ui import render_api_error


def stock_view(rows):
    frame = pd.DataFrame(rows)
    fields = {
        "symbol": "Stock",
        "signal": "Technical signal",
        "institutional_activity": "Institutional activity",
        "stock_rating": "Combined rating",
        "rating_score": "Rating /100",
        "data_status": "Technical data",
        "rating_data_coverage": "Institutional coverage",
        "rating_disclosure_time": "Disclosure time",
    }
    for column in fields:
        if column not in frame:
            frame[column] = None if column == "rating_score" else "Unknown"
    for column in fields:
        if column != "rating_score":
            frame[column] = frame[column].fillna("Unknown")
    # A historical setup on stale candles is not a current actionable signal.
    stale = frame["data_status"].eq("STALE")
    frame.loc[stale, "signal"] = "WAIT · stale candles"
    return frame[list(fields)].rename(columns=fields)


def render_stock_results(rows, *, strategy_id=None, horizon=None):
    st.subheader("Stocks & signals")
    if not rows:
        st.info("No stock results were saved for this run.")
        return
    st.caption(
        "Technical setups and disclosed activity are separate. Missing "
        "institutional evidence is Unknown, with no rating score. "
        "Signals do not place orders."
    )
    query = st.text_input("Find stock", key="tf_scanner_result_search")
    selected = [
        row
        for row in rows
        if query.strip().upper() in str(row.get("symbol", "")).upper()
    ]
    st.dataframe(market_frame(stock_view(selected)), hide_index=True, width="stretch")
    from webapp.evidence_panel import evaluation_evidence

    evaluation_evidence(selected, key="tf_scanner_evidence_stock")
    from webapp.stock_report_workspace import report_link

    report_link(
        [r["symbol"] for r in selected if r.get("symbol")],
        key="scan_results",
        strategy_id=strategy_id,
        horizon=horizon,
    )
    with st.expander("Data issues & complete indicator evidence"):
        failed = [
            row
            for row in selected
            if row.get("signal") == "ERROR"
            or row.get("data_status") in {"UNAVAILABLE", "WARMING_UP", "STALE"}
        ]
        if failed:
            frame = pd.DataFrame(failed)
            cols = [
                name
                for name in (
                    "symbol",
                    "data_status",
                    "data_code",
                    "data_reason",
                    "bar_at",
                    "rating_reason",
                    "rating_data_coverage",
                    "error",
                    "observed_daily_bars",
                    "completed_weekly_bars",
                    "required_completed_weeks",
                )
                if name in frame
            ]
            st.dataframe(frame[cols], hide_index=True, width="stretch")
        else:
            st.caption("No saved data issues in this selection.")
        unavailable = [row for row in selected if row.get("rating_reason")]
        if unavailable:
            st.caption(
                "Rating evidence: a combined score needs actual institutional trades."
            )
            st.dataframe(
                pd.DataFrame(unavailable).reindex(
                    columns=[
                        "symbol",
                        "rating_reason",
                        "rating_data_coverage",
                        "bar_at",
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        st.dataframe(pd.DataFrame(selected), hide_index=True, width="stretch")


@st.fragment(run_every=15)
def render_batch_results(client, batch_id):
    try:
        batch = client.get_json("/reports/batches/" + batch_id, timeout=20)
        if not isinstance(batch, dict) or batch.get("status") not in {
            "queued",
            "running",
            "completed",
            "failed",
            "interrupted",
        }:
            raise ApiError("The backend returned an incomplete run status")
        status = batch["status"]
        if status in {"queued", "running"}:
            from webapp.report_workspace import phase_progress

            done, total, label = phase_progress(batch)
            st.progress(min(1.0, max(0.0, done / max(1, total))), text=label)
            st.caption(
                "This run continues on the server. Results refresh here every "
                "15 seconds."
            )
        elif status != "completed":
            from services.research_failure import failure_message

            st.error(
                failure_message(batch.get("error_code"))
                or "This run did not complete. Open Reports for the saved diagnostic."
            )
        report = batch.get("report") or {}
        if report.get("report_type") == "scanner_indicator_snapshot":
            render_stock_results(
                report["rows"],
                strategy_id=report.get("strategy_id"),
                horizon=report.get("horizon"),
            )
        elif report.get("report_type") == "research_partition_manifest":
            st.caption(
                "Choose one completed stock/strategy batch. Each account is "
                "independent."
            )
            choices = {row["batch_id"]: row for row in report["rows"]}
            child = st.selectbox(
                "Result batch",
                list(choices),
                format_func=lambda value: (
                    f"{choices[value]['strategy_id']} · "
                    f"{choices[value]['stock_count']} stocks · {value[-4:]}"
                ),
            )
            detail = client.get_json("/reports/batches/" + child, timeout=20)
            if detail["kind"] == "scan":
                render_stock_results(
                    detail["report"]["rows"],
                    strategy_id=detail["report"].get("strategy_id"),
                    horizon=detail["report"].get("horizon"),
                )
        elif status == "completed":
            st.success(
                "Backtest completed. Open Backtesting for profitability "
                "and protected Excel trade evidence."
            )
        st.page_link("webapp/pages/reports.py", label="Open scanner reports", icon="↗")
    except ApiError as exc:
        render_api_error(exc, title="Run results unavailable")
