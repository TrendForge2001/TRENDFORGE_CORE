"""Owner controls for actual disclosures and bounded daily confirmation."""

import hashlib
import json

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.ui import render_api_error


def render_trade_import(client):
    with st.expander("Import actual trade disclosures (CSV)"):
        st.caption(
            "Import an NSE bulk/block-deal CSV or the template below. Only exact "
            "tracked investor names or your verified aliases are matched. Each "
            "import replaces activity for its reporting window; earlier snapshots "
            "are retained. Public disclosures do not include every trade."
        )
        st.link_button(
            "NSE bulk / block-deal downloads",
            "https://www.nseindia.com/report-detail/display-bulk-and-block-deals",
        )
        if st.button("Prepare trade CSV template"):
            try:
                data = client.get_bytes("/institutional/big-shark/trades/template")
                st.download_button(
                    "Download trade CSV template",
                    data,
                    "Big_Shark_Trades_Template.csv",
                    mime="text/csv",
                )
            except ApiError as exc:
                render_api_error(exc, title="Trade template unavailable")
        with st.form("tf_big_shark_trade_import"):
            upload = st.file_uploader(
                "Actual trade CSV",
                type=["csv"],
                max_upload_size=2,
                key="tf_big_shark_trade_csv_file",
            )
            source = st.selectbox(
                "Disclosure source", ("NSE_BULK", "NSE_BLOCK", "OWNER_CSV")
            )
            metric = st.selectbox(
                "Compare actual trades by",
                ("quantity", "value"),
                format_func=lambda v: "Shares" if v == "quantity" else "INR value",
            )
            start = st.date_input("Reporting window start (optional)", value=None)
            end = st.date_input("Reporting window end (optional)", value=None)
            disclosed = st.text_input(
                "Source disclosure time (optional)",
                help=(
                    "Use the actual publication timestamp with timezone, for example "
                    "2026-01-05T18:00:00+05:30. Leave blank when unknown; trade date "
                    "and import time are not publication time."
                ),
            )
            aliases = st.text_area(
                "Verified investor aliases (optional JSON)",
                value="{}",
                help=(
                    'Map an exact feed name to an investor in your workbook: {"Feed '
                    'Name": "Portfolio Name"}. No fuzzy matches.'
                ),
            )
            submit = st.form_submit_button("Import trade disclosures", type="primary")
        if submit:
            if upload is None:
                st.warning("Choose a trade CSV first.")
                return
            try:
                json.loads(aliases)
                receipt = client.upload_file(
                    "/institutional/big-shark/trades/import",
                    filename="trades.csv",
                    file_obj=upload,
                    content_type="text/csv",
                    form={
                        "source": source,
                        "metric": metric,
                        "investor_aliases": aliases,
                        "period_start": start.isoformat() if start else "",
                        "period_end": end.isoformat() if end else "",
                        "disclosed_at": disclosed,
                    },
                )
                st.session_state.pop("tf_big_shark_filter_snapshot", None)
                summary = receipt.get("activity_import", {})
                st.success(
                    "Trade disclosures imported: "
                    f"{summary.get('matched_records', 0)} matched records."
                )
                if summary.get("unmatched_records"):
                    st.info(
                        f"{summary['unmatched_records']} records did not match "
                        "tracked investors. Review exact names or verified aliases."
                    )
            except ValueError:
                st.error("Investor aliases must be valid JSON.")
            except ApiError as exc:
                render_api_error(exc, title="Trade import did not complete")


def render_daily_confirmation(client, snapshot):
    with st.expander("Check daily technical confirmation"):
        st.caption(
            "Completed daily Kite candles only. BUY requires price > VWMA20 > "
            "VWMA50, RSI14 55–75, volume ≥1.5× SMA20 and a fresh yearly Fibonacci "
            "R1/R2/R3 breakout. SELL/EXIT requires RSI14 <50 and a fresh VWMA20 "
            "or yearly support breakdown. Annual levels use the previous completed "
            "year. This confirms matching activity; it does not submit an order."
        )
        choices = [r["symbol"] for r in snapshot.get("signals", []) if r.get("symbol")]
        scope = hashlib.sha256("|".join(choices).encode()).hexdigest()[:12]
        remembered = st.session_state.get("tf_big_shark_confirmation_symbol")
        index = choices.index(remembered) if remembered in choices else 0
        symbol = st.selectbox(
            "Stock to confirm",
            choices,
            index=index,
            key="tf_big_shark_confirmation_choice_" + scope,
        )
        st.session_state["tf_big_shark_confirmation_symbol"] = symbol
        checked = st.button(
            "Check daily confirmation",
            disabled=not choices,
            key="tf_big_shark_check_daily_" + scope,
        )
        if checked and not symbol:
            st.warning("Choose at least one stock for daily confirmation.")
        if checked and symbol:
            try:
                snapshot = client.post_json(
                    "/institutional/big-shark/confirm",
                    {"snapshot_id": snapshot["snapshot_id"], "symbols": [symbol]},
                    timeout=120,
                )
                st.session_state.pop("tf_big_shark_filter_snapshot", None)
            except ApiError as exc:
                render_api_error(exc, title="Daily confirmation unavailable")
    return snapshot


def activity_frame(rows):
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for field in ("disclosure_time", "technical_checked_at"):
        if field in frame:
            values = pd.to_datetime(frame[field], utc=True, errors="coerce")
            frame[field] = (
                values.dt.tz_convert("Asia/Kolkata")
                .dt.strftime("%Y-%m-%d %H:%M:%S IST")
                .fillna("Unknown")
            )
    columns = [
        "stock",
        "symbol",
        "activity_signal",
        "technical_confirmation",
        "data_coverage",
        "disclosure_time",
        "technical_checked_at",
        "avg_buy",
        "avg_sell",
        "units",
        "buyers",
        "sellers",
        "period_start",
        "period_end",
    ]
    return frame[[c for c in columns if c in frame]].rename(
        columns={
            "stock": "Stock",
            "symbol": "Symbol",
            "activity_signal": "Activity Signal",
            "technical_confirmation": "Technical Confirmation",
            "data_coverage": "Data Coverage",
            "disclosure_time": "Disclosure Time",
            "technical_checked_at": "Technical Checked At",
            "avg_buy": "Average Buying",
            "avg_sell": "Average Selling",
        }
    )
