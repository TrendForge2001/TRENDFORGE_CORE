"""Paper trade reports belong in Paper Trading, independently of scanner history."""

from io import BytesIO

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.downloads import download_link
from webapp.paper_excel import safe_spreadsheet_frame
from webapp.trade_table import trade_frame
from webapp.ui import render_api_error


def workbook(report):
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        for name, rows, closed in (
            ("Closed paper trades", report["closed_trades"], True),
            ("Open paper positions", report["portfolio"]["positions"], False),
        ):
            frame = trade_frame(rows, closed=closed).reset_index()
            safe_spreadsheet_frame(frame).to_excel(writer, sheet_name=name, index=False)
        records = pd.DataFrame(report["closed_trades"])
        records = records.map(lambda v: str(v) if isinstance(v, (dict, list)) else v)
        safe_spreadsheet_frame(records).to_excel(
            writer, sheet_name="Recorded fill evidence", index=False
        )
        safe_spreadsheet_frame(
            pd.DataFrame(
                [
                    {"Field": key, "Value": report.get(key)}
                    for key in ("period", "period_start", "period_end", "accounting")
                ]
            )
        ).to_excel(writer, sheet_name="Statement basis", index=False)
    return stream.getvalue()


def render_trade_reports(client, *, report=None):
    st.subheader("Paper trade reports")
    period = st.selectbox(
        "Trade report period",
        ["all", "daily", "weekly", "monthly", "yearly"],
        format_func=lambda p: "All time" if p == "all" else p.title(),
        key="tf_paper_report_period",
    )
    try:
        if not isinstance(report, dict) or report.get("period") != period:
            report = client.get_json("/paper/trade-reports", params={"period": period})
        if report.get("scope") != "paper_trade_reports":
            raise ApiError("Paper trade report is incomplete")
        rows = report["closed_trades"]
        summary = report["summary"]
        one, two = st.columns(2)
        one.metric("Closed exit fills", summary["closed_fills"])
        two.metric("Realised P&L", f"₹{summary['realized_pnl']:,.2f}")
        query = (
            st.text_input("Find paper trade", key="tf_paper_report_search")
            .strip()
            .upper()
        )
        selected = [row for row in rows if query in row["symbol"].upper()]
        if selected:
            st.dataframe(trade_frame(selected, closed=True), width="stretch")
        else:
            st.info("No closed paper trades in this selection.")
        st.caption(report["accounting"])
        st.caption(
            "OPEN/CLOSE PRICE are simulated trade entry/exit fills. "
            "Stock, exit time and fill ID identify each row. "
            "NSE/EQ identifies this app's equity paper book."
        )
        download_link(
            "Download paper trade report (.xlsx)",
            workbook(report),
            f"trendforge-paper-trades-{period}.xlsx",
        )
    except ApiError as exc:
        render_api_error(exc, title="Paper trade report unavailable")
    except (ValueError, KeyError, TypeError):
        st.error("Paper trade accounting is incomplete; a report cannot be displayed.")
