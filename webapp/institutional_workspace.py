"""Private institutional setup and evidence, separated from everyday screening."""

import json

import streamlit as st

from webapp.api_client import ApiError
from webapp.institutional_activity import (
    activity_frame,
    render_daily_confirmation,
    render_trade_import,
    workbook_revision,
)
from webapp.institutional_sources import render_public_sources
from webapp.ui import render_api_error


def workbook_import(client):
    st.caption(
        "Your workbook stays in your private workspace. Holdings alone "
        "never generate BUY or SELL activity."
    )
    with st.form("tf_big_shark_import"):
        upload = st.file_uploader(
            "Big Shark workbook", type=["xlsx"], max_upload_size=2
        )
        period = st.text_input("Reporting quarter (optional, YYYY-Q1 to YYYY-Q4)")
        metric = st.selectbox(
            "Actual trade metric",
            ("quantity", "value"),
            format_func=lambda v: (
                "Shares bought/sold" if v == "quantity" else "INR traded value"
            ),
        )
        mapping = st.text_area(
            "Verified NSE symbol mapping (JSON)",
            value="{}",
            help=(
                "Use verified exact company-to-NSE-symbol mappings. Names are "
                "never guessed."
            ),
        )
        submitted = st.form_submit_button("Import and recalculate", type="primary")
    if submitted:
        if upload is None:
            st.warning("Choose an XLSX workbook first.")
        else:
            try:
                json.loads(mapping)
                client.upload_file(
                    "/institutional/big-shark/import",
                    filename="portfolio.xlsx",
                    file_obj=upload,
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    form={
                        "symbol_map": mapping,
                        "reporting_period": period,
                        "metric": metric,
                    },
                )
                st.session_state.pop("tf_big_shark_filter_snapshot", None)
                st.success("Private workbook imported and recalculated.")
            except ValueError:
                st.error("Symbol mapping must be valid JSON.")
            except ApiError as exc:
                render_api_error(exc, title="Workbook import unavailable")
    render_trade_import(client)


def activity_workspace(client):
    horizon = st.selectbox(
        "Stock rating horizon",
        ("short_term", "long_term"),
        format_func=lambda v: (
            "Short Term · Daily" if v == "short_term" else "Long Term · Daily trend"
        ),
    )
    try:
        snapshot = client.get_json(
            "/institutional/big-shark", params={"horizon": horizon}
        )
    except ApiError as exc:
        if exc.status_code == 404:
            st.info(
                "Add a tracked investor workbook or refresh a supported "
                "holdings source. Market disclosures remain available on "
                "Public feeds."
            )
        else:
            render_api_error(exc, title="Institutional activity unavailable")
        return
    snapshot = render_daily_confirmation(client, snapshot, horizon=horizon)
    rows = snapshot.get("signals", [])
    actual = sum(bool(row.get("observations")) for row in rows)
    st.caption(
        f"{len(rows)} tracked stocks · {actual} with actual trade observations · "
        f"Updated {snapshot.get('imported_at', 'unknown')}"
    )
    st.caption(
        "Disclosed buying/selling is compared per investor. Ratings "
        "use 40 institutional + 60 technical points; missing or stale "
        "evidence receives no score."
    )
    rating_filter = st.selectbox(
        "Stock rating filter",
        [
            "All ratings",
            "STRONG_BUY",
            "BUY",
            "WATCH",
            "HOLD",
            "EXIT",
            "CONFLICT",
            "INSUFFICIENT_DATA",
        ],
    )
    if rating_filter != "All ratings":
        rows = [
            row
            for row in rows
            if row.get("stock_rating", "INSUFFICIENT_DATA") == rating_filter
        ]
    full = activity_frame(rows)
    compact = [
        name
        for name in (
            "Symbol",
            "Stock",
            "Activity Signal",
            "Technical Confirmation",
            "Stock rating",
            "Confluence score / 100",
            "Data Coverage",
            "Disclosure Time",
        )
        if name in full
    ]
    st.dataframe(full[compact], hide_index=True, width="stretch")
    with st.expander("Review disclosure and technical evidence"):
        st.dataframe(full, hide_index=True, width="stretch")
        names = {row.get("symbol") or row["stock"]: row for row in rows}
        chosen = st.selectbox("Stock evidence", list(names)) if names else None
        if chosen:
            row = names[chosen]
            st.json(
                {
                    "source": snapshot.get("activity_source", "Uploaded workbook"),
                    "first_seen_at": row.get("first_seen_at"),
                    "disclosure_time_basis": row.get("disclosure_time_basis"),
                    "technical_evidence": row.get("technical_evidence", {}),
                    "rating_evidence": row.get("rating_evidence", {}),
                    "rating_technicals": (row.get("rating_technicals") or {}).get(
                        horizon, {}
                    ),
                }
            )
    revision = workbook_revision(snapshot)
    if st.button("Prepare refreshed workbook"):
        try:
            st.session_state["tf_big_shark_prepared_workbook"] = (
                revision,
                client.get_bytes("/institutional/big-shark/workbook"),
            )
        except ApiError as exc:
            render_api_error(exc, title="Workbook unavailable")
    prepared = st.session_state.get("tf_big_shark_prepared_workbook")
    if prepared and prepared[0] != revision:
        st.session_state.pop("tf_big_shark_prepared_workbook", None)
    elif prepared:
        st.download_button(
            "Download recalculated sheets",
            prepared[1],
            "Big_Shark_Recalculated.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            on_click="ignore",
        )


def institutional_workspace(client, *, key="institutional_data"):
    tabs = st.tabs(
        ["Public feeds", "Private imports", "Activity & ratings"],
        key=key,
        on_change="rerun",
    )
    with tabs[0]:
        if tabs[0].open:
            render_public_sources(client, expanded=True)
    with tabs[1]:
        if tabs[1].open:
            workbook_import(client)
    with tabs[2]:
        if tabs[2].open:
            activity_workspace(client)
