"""Private portfolio workspace; ownership signals never submit broker orders."""

import hashlib
import json

import streamlit as st

from webapp.api_client import ApiError
from webapp.institutional_activity import (
    activity_frame,
    render_daily_confirmation,
    render_trade_import,
)
from webapp.institutional_sources import render_public_sources
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
public_state = render_public_sources(client)
if public_state and any(
    name.startswith("NSE_") for name in public_state.get("failures", {})
):
    st.warning(
        "The latest public trade refresh failed. Activity labels below retain "
        "the previous successful reporting window; review its dates before use."
    )
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
rating_horizon = st.selectbox(
    "Stock rating horizon",
    ("short_term", "long_term"),
    format_func=lambda value: (
        "Short Term · Daily" if value == "short_term" else "Long Term · Daily trend"
    ),
)
try:
    snapshot = client.get_json(
        "/institutional/big-shark"
        + ("?horizon=long_term" if rating_horizon == "long_term" else "")
    )
except ApiError as exc:
    if exc.status_code == 404:
        st.info("Import your private workbook to populate this scanner.")
    else:
        render_api_error(exc, title="Private portfolio unavailable")
    st.stop()

snapshot = render_daily_confirmation(client, snapshot, horizon=rating_horizon)
st.caption(
    "Stock ratings combine actual disclosed activity with completed daily EMA/VWMA, "
    "Wilder RSI14, volume SMA20 and yearly Fibonacci pivots. Score: institutional "
    "40 + technical 60. BUY requires agreement; conflicting evidence is flagged. "
    "Missing or stale data gives Insufficient data. EXIT applies to existing longs; "
    "ratings do not place trades and are not probability estimates."
)
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
rating_filter = st.selectbox(
    "Stock rating filter",
    (
        "All ratings",
        "STRONG_BUY",
        "BUY",
        "WATCH",
        "HOLD",
        "EXIT",
        "CONFLICT",
        "INSUFFICIENT_DATA",
    ),
)
if rating_filter != "All ratings":
    rows = [
        row
        for row in rows
        if row.get("stock_rating", "INSUFFICIENT_DATA") == rating_filter
    ]
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
                "rating_evidence": row.get("rating_evidence", {}),
                "rating_technicals": (row.get("rating_technicals") or {}).get(
                    rating_horizon, {}
                ),
            },
        )
unmapped = sum(not row.get("symbol") for row in snapshot.get("signals", []))
if unmapped:
    st.info(
        f"{unmapped} names need verified NSE symbol mapping "
        "before use in technical stock selection."
    )
workbook_revision = hashlib.sha256(
    json.dumps(snapshot, sort_keys=True, default=str).encode()
).hexdigest()
if st.button("Prepare refreshed workbook"):
    try:
        content = client.get_bytes("/institutional/big-shark/workbook")
        st.session_state["tf_big_shark_prepared_workbook"] = (
            workbook_revision,
            content,
        )
    except ApiError as exc:
        render_api_error(exc, title="Workbook unavailable")
prepared = st.session_state.get("tf_big_shark_prepared_workbook")
if prepared and prepared[0] != workbook_revision:
    st.session_state.pop("tf_big_shark_prepared_workbook", None)
    prepared = None
if prepared and prepared[0] == workbook_revision:
    st.download_button(
        "Download recalculated sheets",
        prepared[1],
        "Big_Shark_Recalculated.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        on_click="ignore",
    )
st.caption(
    "More AMC and institutional conditions are reserved for your later instructions."
)
