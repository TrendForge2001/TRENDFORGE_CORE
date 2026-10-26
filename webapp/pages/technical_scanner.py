"""Kite-only technical indicator scanner with read-only signal results."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.paper_excel import safe_csv_bytes
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import page_header, render_api_error
from webapp.nifty_selection import select_nifty_stocks, scan_nifty_stocks
from scanner.workspace_strategies import strategy_choices
from webapp.scanner_backtesting import scanner_description

page_header(
    "Technical Indicator Scanner",
    "Intraday and swing technical signals generated from Kite OHLCV candles, without fundamental gates.",
    kicker="02 / Scanner",
)
from webapp.strategy_catalog import clear_retired_scan_cache
clear_retired_scan_cache()
client = api_client(timeout=240)
try:
    readiness = client.get_json("/technical/readiness")
except ApiError as exc:
    render_api_error(exc, title="Technical engine unavailable")
    st.stop()

r1, r2, r3 = st.columns(3)
r1.metric("Source", str(readiness.get("data_policy") or "KITE_ONLY").upper())
r2.metric("Intraday candles", str((readiness.get("profiles") or {}).get("intraday", {}).get("interval") or "15m"))
r3.metric("Swing candles", str((readiness.get("profiles") or {}).get("swing", {}).get("interval") or "1d"))
st.caption("Choose a scanner below. Each stock score describes the selected strategy’s technical checks. No fundamental or corporate-action filters are applied.")

mode = st.radio("Trading mode", ["intraday", "swing", "positional"], horizontal=True, format_func=lambda value: "Medium / Long term" if value == "positional" else value.title())
choices = strategy_choices(mode)
strategy_label = st.selectbox("Scanner / strategy", list(choices))
strategy_id = choices[strategy_label]
if mode == "positional":
    from webapp.strategy_catalog import render_review_scanner
    render_review_scanner(client, strategy_id, key="technical_scanner_review")
    st.stop()
profile = scanner_description(mode, strategy_id)
st.caption("Indicators applied: " + profile["indicators"])
with st.expander("Scanner conditions"):
    st.write(profile["conditions"])
selection = select_nifty_stocks(client, key="technical_universe")
with st.form("tf_r726_technical_scan"):
    c1, c2 = st.columns(2)
    with c1:
        period = st.selectbox("Kite candle history", ["30d", "45d", "60d"] if mode == "intraday" else ["1y", "2y", "5y"], index=2 if mode == "intraday" else 1)
    with c2:
        top_n = st.number_input("Max BUY candidates", min_value=1, max_value=100, value=20)
    submitted = st.form_submit_button("Run technical scan", type="primary", disabled=not admin_key_configured())

if submitted:
    st.session_state.pop("tf_r726_scan_result", None)
    if not selection["symbols"]:
        st.error("Select stocks from a Nifty list.")
    else:
        try:
            result = scan_nifty_stocks(
                client, selection, mode=mode, period=period,
                strategy_id=strategy_id, top_n=int(top_n),
            )
            count_fields = ("requested_symbols", "completed_symbols", "error_symbols", "buy_candidates")
            counts_valid = all(type(result.get(name)) is int and result[name] >= 0 for name in count_fields)
            rows = result.get("results")
            if (
                result.get("status") != "completed"
                or not counts_valid
                or result["completed_symbols"] + result["error_symbols"] != result["requested_symbols"]
                or not isinstance(rows, list)
                or not all(isinstance(row, dict) for row in rows)
            ):
                raise ApiError("The backend returned an invalid technical scan result")
            st.session_state["tf_r726_scan_result"] = {
                **result, "observed_at": datetime.now(timezone.utc).isoformat(),
            }
        except ApiError as exc:
            render_api_error(exc, title="Kite technical scan failed")

if not admin_key_configured():
    st.info("Enter the Admin API Key at sign-in to run a scanner. Scanning never places live broker orders.")

result = st.session_state.get("tf_r726_scan_result")
if isinstance(result, dict):
    if result.get("mode") and result.get("period"):
        st.caption(f"Displayed result: {result['mode']} · {result['period']} · {scanner_description(result['mode'], result.get('strategy_id'))['scanner']}")
    x1, x2, x3 = st.columns(3)
    x1.metric("Processed", int(result.get("completed_symbols") or 0))
    x2.metric("Errors", int(result.get("error_symbols") or 0))
    x3.metric("BUY candidates", int(result.get("buy_candidates") or 0))
    matches = result.get("results")
    matches = matches if isinstance(matches, list) else []
    if matches:
        df = pd.DataFrame(matches)
        preferred = [
            "symbol", "signal", "score", "confidence", "trigger", "entry",
            "stoploss", "target2", "reward_risk", "bar_at", "error",
        ]
        st.subheader("Scanner results")
        st.dataframe(df[[c for c in preferred if c in df.columns]], use_container_width=True, hide_index=True)
        st.download_button("Export scanner results (CSV)", safe_csv_bytes(df), file_name="trendforge_technical_scan.csv", mime="text/csv")
    else:
        st.info("Scan completed with no eligible technical signals.")
    if result.get("errors"):
        with st.expander("Provider or symbol errors"):
            st.json(result["errors"])
    st.caption("Scanner results are research signals, not broker orders.")
    st.info("Open Kite Backtesting → Scanner matches to filter these stocks and compare historical results.")

if isinstance(result, dict):
    from webapp.paper_handoff import render_scanner_paper_handoff
    render_scanner_paper_handoff(client, result)
