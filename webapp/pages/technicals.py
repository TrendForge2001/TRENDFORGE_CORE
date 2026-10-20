"""NIFTY 500 technical scanner, paper automation and R71.5 backtesting."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Technical Scanner & Backtesting",
    "NIFTY 500 technical-only intraday and swing scanning using Kite candles, with paper-only auto-entry and R71.5 realistic backtesting.",
    kicker="Technicals",
)

client = api_client(timeout=120)


def safe_get(path: str):
    try:
        return client.get_json(path)
    except ApiError:
        return {}


readiness = safe_get("/technical/readiness")
auto = safe_get("/workspace/technical/auto-status")
paper = safe_get("/paper/readiness")
auto_entry = safe_get("/paper/auto-entry/readiness")

r1, r2, r3, r4, r5 = st.columns(5)
with r1:
    market = readiness.get("market_data")
    market = market if isinstance(market, dict) else {}
    st.metric("Kite", str(market.get("status") or "unknown").upper())
with r2:
    st.metric("Auto scanner", str(auto.get("status") or "unknown").upper())
with r3:
    st.metric("Paper trading", str(paper.get("status") or "unknown").upper())
with r4:
    st.metric("Auto-entry", "ON" if auto_entry.get("enabled") else "OFF")
with r5:
    st.metric("Kill switch", "ON" if paper.get("kill_switch") else "OFF")

info_note(
    "Technical path only: fundamentals/enrichment are excluded. Broker orders remain disabled. Scheduled paper entries use the existing R67.2 risk gate."
)

st.subheader("Tomorrow automation")
schedule_cols = st.columns(4)
with schedule_cols[0]:
    st.metric("Universe", str(auto.get("universe") or "NIFTY 500"))
with schedule_cols[1]:
    st.metric("Swing scan", str(auto.get("swing_time_ist") or "09:25") + " IST")
with schedule_cols[2]:
    st.metric(
        "Intraday window",
        f"{auto.get('intraday_start_ist') or '09:30'}–{auto.get('intraday_end_ist') or '14:45'}",
    )
with schedule_cols[3]:
    st.metric("Auto paper", "ON" if auto.get("paper_execution") else "OFF")

if auto.get("status") == "disabled":
    st.warning("Automatic technical scanning is disabled in the backend environment.")

st.subheader("Manual NIFTY 500 scanner")
manual_paper = st.toggle(
    "Allow approved paper entries for this manual scan",
    value=False,
    help="Still subject to paper auto-entry score/confidence, RR, capital, daily-loss, position-count and market-hours gates.",
)
b1, b2, b3 = st.columns(3)
with b1:
    run_intraday = st.button(
        "Run NIFTY 500 Intraday",
        type="primary",
        use_container_width=True,
    )
with b2:
    run_swing = st.button(
        "Run NIFTY 500 Swing",
        use_container_width=True,
    )
with b3:
    refresh = st.button("Refresh status", use_container_width=True)

if run_intraday or run_swing:
    if not admin_key_configured():
        st.error("Enter the Admin API Key at sign-in or System session state first.")
    else:
        mode = "intraday" if run_intraday else "swing"
        try:
            response = client.post_json(
                "/workspace/technical/run",
                {
                    "mode": mode,
                    "execute_paper": bool(manual_paper),
                },
                timeout=30,
            )
            st.success(
                f"{mode.title()} NIFTY 500 scan: {response.get('status', 'started')}."
            )
            st.rerun()
        except ApiError as exc:
            render_api_error(exc, title="Technical scan start failed")

if refresh:
    st.rerun()

auto = safe_get("/workspace/technical/auto-status")
last = auto.get("last_results")
last = last if isinstance(last, dict) else {}
for mode in ("intraday", "swing"):
    result = last.get(mode)
    if not isinstance(result, dict):
        continue
    st.markdown(f"**Latest {mode.title()} run**")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Completed", int(result.get("completed_symbols") or 0))
    with c2:
        st.metric("Errors", int(result.get("error_symbols") or 0))
    with c3:
        st.metric("BUY candidates", int(result.get("buy_candidates") or 0))
    with c4:
        p = result.get("paper")
        p = p if isinstance(p, dict) else {}
        st.metric("Paper", str(p.get("status") or "n/a").upper())
    picks = result.get("top_picks")
    picks = picks if isinstance(picks, list) else []
    if picks:
        frame = pd.DataFrame(picks)
        preferred = [
            "symbol", "score", "confidence", "trigger",
            "entry", "stoploss", "target2", "reward_risk",
        ]
        st.dataframe(
            frame[[c for c in preferred if c in frame.columns]],
            use_container_width=True,
            hide_index=True,
        )

st.divider()
st.subheader("R71.5 NIFTY 100 / 200 / 500 realistic backtesting")
st.caption(
    "Runs both swing and intraday realistic backtests with ATR stop/target logic, costs/slippage, and 15:00 IST intraday exit. The export contains the P&L workbook."
)

validation = safe_get("/technical/validation/status")
v1, v2, v3 = st.columns(3)
with v1:
    st.metric("Validation", str(validation.get("status") or "not started").upper())
with v2:
    progress = validation.get("progress")
    progress = progress if isinstance(progress, dict) else {}
    st.metric("Phase", str(progress.get("phase") or "—"))
with v3:
    st.metric("Run ID", str(validation.get("run_id") or "—"))

run_validation = st.button(
    "Run NIFTY 100/200/500 Backtesting",
    use_container_width=True,
)
if run_validation:
    if not admin_key_configured():
        st.error("Admin API Key is required to initiate the batch backtest.")
    else:
        try:
            response = client.post_json(
                "/technical/validation/run",
                {
                    "capital": 100000.0,
                    "chunk_size": 25,
                    "force": False,
                },
                timeout=30,
            )
            token = response.get("export_token")
            if token:
                st.session_state["tf_r715_export_token"] = token
            st.success(
                f"Validation {response.get('status', 'started')} · {response.get('run_id', '')}"
            )
            st.rerun()
        except ApiError as exc:
            render_api_error(exc, title="Backtest validation start failed")

token = str(st.session_state.get("tf_r715_export_token") or "").strip()
if token:
    try:
        workbook = client.get_bytes(
            "/technical/validation/export",
            params={"token": token},
            timeout=120,
        )
        st.download_button(
            "Download R71.5 P&L Excel",
            data=workbook,
            file_name="TrendForge_R71_5_NIFTY_Technical_PnL.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except ApiError:
        st.caption("P&L workbook becomes available after the validation run completes.")
