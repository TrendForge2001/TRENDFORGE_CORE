"""Private portfolio workspace; ownership signals never submit broker orders."""

import json

import streamlit as st

from webapp.api_client import ApiError
from webapp.institutional_activity import (
    activity_frame,
    render_daily_confirmation,
    render_trade_import,
)
from webapp.runtime import api_client
from webapp.ui import page_header, render_api_error

page_header(
    "Institutional Scanner", "AMC / Big Shark / Institutional ownership signals."
)
st.markdown(
    "**BUY:** average actual buying exceeds average actual selling. "
    "**SELL:** average actual selling exceeds average actual buying. "
    "Equal averages give HOLD."
)
st.caption(
    "Use one metric: actual share quantities or actual traded INR values. "
    "Average buying is per buying investor; average selling is per selling investor. "
    "Current holdings and quarterly ownership changes do not produce trade signals."
)
client = api_client(timeout=45)
with st.expander("Import / refresh private workbook"):
    st.caption(
        "Upload a new source workbook to refresh the stored sheets. Only uploaded "
        "values are recalculated; no live filings are claimed."
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
                "Map workbook names to verified NSE symbols, for example "
                '{"Example Company": "EXAMPLE"}. Names are never guessed.'
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
                render_api_error(exc, title="Import could not complete")
render_trade_import(client)
try:
    snapshot = client.get_json("/institutional/big-shark")
except ApiError as exc:
    if exc.status_code == 404:
        st.info("Import your private workbook to populate this scanner.")
    else:
        render_api_error(exc, title="Private portfolio unavailable")
    st.stop()

snapshot = render_daily_confirmation(client, snapshot)
counts = snapshot.get("counts", {})
for column, signal in zip(
    st.columns(4), ("BUY", "SELL", "HOLD", "NO_DATA"), strict=True
):
    column.metric(signal, counts.get(signal, 0))
st.caption("Recalculated: " + str(snapshot.get("imported_at", "Unknown")))
if snapshot.get("activity_source"):
    st.warning(
        "Activity compares matched disclosed trades only. Unreported trading "
        "remains unknown. Disclosure Time is blank unless supplied by the source; "
        "first-seen time is recorded separately. Technical confirmation is a "
        "dated check, not a trade execution."
    )
else:
    st.warning(
        "Source quarter: " + str(snapshot.get("reporting_period") or "UNKNOWN") + ". "
        "Live source filings have not been verified. Import actual trade "
        "disclosures or fill the TRADE FLOWS sheet to calculate activity. "
        "Missing observations remain unknown."
    )
rows = snapshot.get("signals", [])
signal = st.session_state.get("tf_institutional_signal_filter", "All stocks")
if signal != "All stocks":
    rows = [row for row in rows if row.get("signal") == signal]
st.dataframe(activity_frame(rows), hide_index=True, width="stretch")
with st.expander("Review disclosure and technical evidence"):
    for row in rows:
        st.write(
            row.get("stock"),
            {
                "source": snapshot.get("activity_source", "Uploaded workbook"),
                "first_seen_at": row.get("first_seen_at"),
                "disclosure_time_basis": row.get("disclosure_time_basis"),
                "technical_evidence": row.get("technical_evidence", {}),
            },
        )
unmapped = sum(not row.get("symbol") for row in snapshot.get("signals", []))
if unmapped:
    st.info(
        f"{unmapped} names need verified NSE symbol mapping "
        "before use in technical stock selection."
    )
if st.button("Prepare refreshed workbook"):
    try:
        content = client.get_bytes("/institutional/big-shark/workbook")
        st.download_button(
            "Download recalculated sheets",
            content,
            "Big_Shark_Recalculated.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except ApiError as exc:
        render_api_error(exc, title="Workbook unavailable")
st.caption(
    "More AMC and institutional conditions are reserved for your later instructions."
)
