"""Fundamental data management page."""
from __future__ import annotations

import mimetypes

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import (
    info_note,
    page_header,
    render_api_error,
    report_rows,
)


page_header(
    "Fundamentals",
    "Inspect SQLite fundamentals, identify incomplete coverage, upload curated CSV/XLSX data, and maintain symbol-level values with backend evidence preserved.",
    kicker="Data",
)

client = api_client(timeout=60)

try:
    readiness = client.get_json(
        "/fundamentals/readiness",
        params={"limit": 5000},
        timeout=60,
    )
    r1, r2, r3, r4, r5 = st.columns(5)
    with r1:
        st.metric(
            "NIFTY500 symbols",
            readiness.get("tradable_symbols", 0),
        )
    with r2:
        st.metric(
            "SQLite records",
            readiness.get("database_records", 0),
        )
    with r3:
        st.metric(
            "DB coverage",
            f"{float(readiness.get('database_coverage_pct', 0) or 0):.1f}%",
        )
    with r4:
        st.metric(
            "Scanner data-ready",
            readiness.get("scanner_ready_records", 0),
        )
    with r5:
        st.metric(
            "Scanner data readiness",
            f"{float(readiness.get('scanner_readiness_pct', 0) or 0):.1f}%",
        )

    readiness_counts = readiness.get("scanner_readiness_counts")
    if not isinstance(readiness_counts, dict):
        readiness_counts = readiness.get("readiness_counts")
    field_coverage = readiness.get("field_coverage")
    with st.expander("R69.4 coverage & readiness", expanded=True):
        left_readiness, right_coverage = st.columns(2)
        with left_readiness:
            st.markdown("**Readiness states**")
            if isinstance(readiness_counts, dict) and readiness_counts:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"Status": key, "Count": value}
                            for key, value in readiness_counts.items()
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
        with right_coverage:
            st.markdown("**Mandatory field coverage**")
            if isinstance(field_coverage, dict) and field_coverage:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Field": field,
                                "Present": values.get("present", 0),
                                "Missing": values.get("missing", 0),
                                "Invalid": values.get("invalid", 0),
                                "Coverage %": values.get("coverage_pct", 0),
                                "Fresh %": values.get(
                                    "fresh_coverage_pct",
                                    0,
                                ),
                            }
                            for field, values in field_coverage.items()
                            if isinstance(values, dict)
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
except ApiError as exc:
    readiness = {}
    st.warning(f"R69.4 readiness unavailable: {exc}")

filters = st.columns(4)
with filters[0]:
    limit = st.number_input(
        "Rows",
        min_value=1,
        max_value=5000,
        value=500,
        step=50,
    )
with filters[1]:
    incomplete_only = st.toggle("Incomplete only", value=False)
with filters[2]:
    stale_only = st.toggle("Stale only", value=False)
with filters[3]:
    refresh = st.button(
        "Refresh",
        type="primary",
        use_container_width=True,
    )

if refresh:
    st.rerun()

try:
    report = client.get_json(
        "/fundamentals",
        params={
            "limit": int(limit),
            "incomplete_only": str(incomplete_only).lower(),
            "stale_only": str(stale_only).lower(),
        },
        timeout=60,
    )
    rows = report_rows(report)
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No fundamental rows matched the current filters.")
        with st.expander("Raw report"):
            st.json(report)
except ApiError as exc:
    render_api_error(exc, title="Fundamental report unavailable")

st.divider()
left, right = st.columns(2)
with left:
    st.subheader("Inspect symbol")
    symbol = (
        st.text_input(
            "Symbol to inspect",
            placeholder="TCS",
            key="fund_symbol",
        )
        .strip()
        .upper()
    )
    if st.button("Load symbol", use_container_width=True) and symbol:
        try:
            st.session_state["tf_fundamental_symbol"] = (
                client.get_json(f"/fundamentals/{symbol}")
            )
        except ApiError as exc:
            render_api_error(exc)

    symbol_payload = st.session_state.get(
        "tf_fundamental_symbol"
    )
    if isinstance(symbol_payload, dict):
        st.json(symbol_payload)

with right:
    st.subheader("Templates")
    try:
        csv_template = client.get_bytes(
            "/fundamentals/template.csv"
        )
        st.download_button(
            "Download CSV template",
            data=csv_template,
            file_name="trendforge_fundamentals_template.csv",
            mime="text/csv",
            use_container_width=True,
        )
    except ApiError as exc:
        st.warning(str(exc))

    try:
        xlsx_template = client.get_bytes(
            "/fundamentals/template.xlsx"
        )
        st.download_button(
            "Download XLSX template",
            data=xlsx_template,
            file_name="trendforge_fundamentals_template.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            use_container_width=True,
        )
    except ApiError as exc:
        st.warning(str(exc))

    try:
        completion_xlsx = client.get_bytes(
            "/fundamentals/completion.xlsx"
        )
        st.download_button(
            "Download NIFTY500 completion workbook",
            data=completion_xlsx,
            file_name="trendforge_fundamental_completion.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            use_container_width=True,
        )
    except ApiError as exc:
        st.warning(str(exc))

st.divider()
st.subheader("Complete missing NIFTY500 fundamentals")
info_note(
    "The R69.4 completion workbook includes incomplete SQLite rows and NIFTY500 constituents with no database row. Preview is read-only; Apply can create a new record only for a verified NIFTY500 member and never overwrites an already-present fundamental field."
)
completion_upload = st.file_uploader(
    "Completion CSV / XLSX / XLSM",
    type=["csv", "xlsx", "xlsm"],
    key="fund_completion_upload",
)
completion_apply = st.toggle(
    "Apply completion after validation",
    value=False,
    key="fund_completion_apply",
)
if not admin_key_configured():
    info_note(
        "Configure production authorization before using the completion upload endpoint.",
        danger=True,
    )

if st.button(
    "Preview / apply completion",
    type="primary",
    disabled=completion_upload is None,
    use_container_width=True,
):
    assert completion_upload is not None
    completion_mime = (
        completion_upload.type
        or mimetypes.guess_type(completion_upload.name)[0]
        or "application/octet-stream"
    )
    try:
        completion_result = client.upload_file(
            "/fundamentals/completion/upload",
            filename=completion_upload.name,
            file_obj=completion_upload,
            content_type=completion_mime,
            form={
                "apply": str(completion_apply).lower(),
                "sheet": "Completion",
            },
            timeout=120,
        )
        if completion_apply:
            st.success("Fundamental completion applied.")
        else:
            st.success("Fundamental completion preview completed.")
        st.json(completion_result)
    except ApiError as exc:
        render_api_error(
            exc,
            title="Fundamental completion failed",
        )

st.divider()
st.subheader("Upload fundamentals")
if not admin_key_configured():
    info_note(
        "Production uploads require the admin key.",
        danger=True,
    )

uploaded = st.file_uploader(
    "CSV / XLSX / XLSM",
    type=["csv", "xlsx", "xlsm"],
)
source = st.text_input(
    "Source label",
    value="manual_upload",
)

if st.button(
    "Import file",
    type="primary",
    disabled=uploaded is None,
):
    assert uploaded is not None
    mime = (
        uploaded.type
        or mimetypes.guess_type(uploaded.name)[0]
        or "application/octet-stream"
    )
    try:
        result = client.upload_file(
            "/fundamentals/upload",
            filename=uploaded.name,
            file_obj=uploaded,
            content_type=mime,
            form={"source": source, "sheet": "0"},
            timeout=120,
        )
        st.success("Fundamental file processed.")
        st.json(result)
    except ApiError as exc:
        render_api_error(
            exc,
            title="Fundamental import failed",
        )

with st.expander("Manual symbol update"):
    edit_symbol = (
        st.text_input(
            "Symbol",
            placeholder="TCS",
            key="fund_edit_symbol",
        )
        .strip()
        .upper()
    )
    fields = {
        "roce": st.text_input(
            "ROCE %",
            key="edit_roce",
        ).strip(),
        "roe": st.text_input(
            "ROE %",
            key="edit_roe",
        ).strip(),
        "sales_growth": st.text_input(
            "Sales growth %",
            key="edit_sales_growth",
        ).strip(),
        "profit_growth": st.text_input(
            "Profit growth %",
            key="edit_profit_growth",
        ).strip(),
        "eps_growth": st.text_input(
            "EPS growth %",
            key="edit_eps_growth",
        ).strip(),
        "debt_equity": st.text_input(
            "Debt / Equity",
            key="edit_debt_equity",
        ).strip(),
        "promoter_holding": st.text_input(
            "Promoter holding %",
            key="edit_promoter",
        ).strip(),
        "pledged": st.text_input(
            "Pledged %",
            key="edit_pledged",
        ).strip(),
    }
    edit_source = st.text_input(
        "Update source",
        value="manual_webapp",
        key="edit_source",
    )

    if st.button("Save symbol update", type="primary"):
        if not edit_symbol:
            st.error("Symbol is required.")
        else:
            payload = {"source": edit_source}
            invalid = []
            for key, raw in fields.items():
                if not raw:
                    continue
                try:
                    payload[key] = float(raw)
                except ValueError:
                    invalid.append(key)

            if invalid:
                st.error(
                    "Invalid numeric fields: "
                    + ", ".join(invalid)
                )
            else:
                try:
                    result = client.put_json(
                        f"/fundamentals/{edit_symbol}",
                        payload,
                    )
                    st.success(
                        "Fundamental values updated."
                    )
                    st.json(result)
                except ApiError as exc:
                    render_api_error(
                        exc,
                        title="Fundamental update failed",
                    )
