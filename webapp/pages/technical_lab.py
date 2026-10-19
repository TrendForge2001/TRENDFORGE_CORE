"""Technical-only intraday/swing scanner, paper and backtest controls."""
from __future__ import annotations

from uuid import uuid4

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Technical Lab",
    "Scan and paper-test technical setups using Kite historical candles, or backtest the same intraday and swing profiles. Fundamentals and enrichment are excluded from this path.",
    kicker="Technical Research",
)

client = api_client(timeout=240)

try:
    readiness = client.get_json("/technical/readiness")
except ApiError as exc:
    render_api_error(
        exc,
        title="Technical trading service unavailable",
    )
    st.stop()

info_note(
    "Kite-only OHLCV. Paper execution remains behind the existing paper kill switch and R67.2 risk gate. Historical backtests never create paper or broker orders."
)

r1, r2, r3, r4 = st.columns(4)
with r1:
    st.metric("Data", str(readiness.get("data_policy") or "unknown").upper())
with r2:
    st.metric(
        "Intraday",
        str(
            (readiness.get("profiles") or {})
            .get("intraday", {})
            .get("interval", "15m")
        ).upper(),
    )
with r3:
    st.metric(
        "Swing",
        str(
            (readiness.get("profiles") or {})
            .get("swing", {})
            .get("interval", "1d")
        ).upper(),
    )
with r4:
    st.metric(
        "Fundamentals",
        "OFF" if not readiness.get("fundamentals_used") else "ON",
    )

market_health = readiness.get("market_data") or {}
if str(market_health.get("status") or "").lower() in {
    "degraded",
    "unavailable",
}:
    info_note(
        "Kite market-data health is degraded. Refresh the current Kite access token before running technical scans or backtests.",
        danger=True,
    )

if not admin_key_configured():
    info_note(
        "Production POST operations require the TrendForge admin key. Configure it before running scans, paper entries, or backtests.",
        danger=True,
    )

st.divider()
st.subheader("Technical scan / paper test")

scan_mode = st.radio(
    "Trading style",
    ["intraday", "swing"],
    horizontal=True,
    format_func=lambda value: value.title(),
    key="tf_technical_scan_mode",
)
scan_periods = (
    ["30d", "45d", "60d"]
    if scan_mode == "intraday"
    else ["1y", "2y", "5y"]
)
default_period_index = 2 if scan_mode == "intraday" else 1

with st.form("technical_scan_form"):
    a, b = st.columns([3, 1])
    with a:
        symbols_text = st.text_area(
            "NSE symbols",
            value="RELIANCE\nTCS\nSBIN",
            height=110,
            help="One symbol per line or comma-separated. Maximum 100.",
        )
    with b:
        scan_period = st.selectbox(
            "History",
            scan_periods,
            index=default_period_index,
        )
        top_n = st.number_input(
            "Top BUY candidates",
            min_value=1,
            max_value=100,
            value=20,
            step=1,
        )
        execute_paper = st.toggle(
            "Execute approved paper entries",
            value=False,
            help=(
                "The technical BUY must still pass the existing paper "
                "auto-entry score, risk, daily-loss, position and kill-switch gates."
            ),
        )

    scan_submit = st.form_submit_button(
        "Run technical scan",
        type="primary",
        use_container_width=True,
    )

if scan_submit:
    symbols = [
        token.strip().upper()
        for line in symbols_text.replace(",", "\n").splitlines()
        for token in [line]
        if token.strip()
    ]
    if not symbols:
        st.error("Enter at least one symbol.")
    elif not admin_key_configured():
        st.error("Configure the production admin key first.")
    else:
        run_id = f"ui-tech-{uuid4().hex[:16]}"
        try:
            with st.spinner(
                f"Running {scan_mode} technical scan from Kite candles..."
            ):
                result = client.post_json(
                    "/technical/scan",
                    {
                        "symbols": symbols,
                        "mode": scan_mode,
                        "period": scan_period,
                        "top_n": int(top_n),
                        "execute_paper": bool(execute_paper),
                        "run_id": run_id,
                    },
                    timeout=240,
                )
            st.session_state["tf_technical_scan_result"] = result
            st.success(
                f"Technical scan completed: {result.get('run_id', run_id)}"
            )
        except ApiError as exc:
            render_api_error(exc, title="Technical scan failed")

scan_result = st.session_state.get("tf_technical_scan_result")
if isinstance(scan_result, dict):
    a, b, c, d = st.columns(4)
    with a:
        st.metric(
            "Completed",
            int(scan_result.get("completed_symbols") or 0),
        )
    with b:
        st.metric(
            "Errors",
            int(scan_result.get("error_symbols") or 0),
        )
    with c:
        st.metric(
            "BUY candidates",
            int(scan_result.get("buy_candidates") or 0),
        )
    with d:
        st.metric(
            "Paper",
            str((scan_result.get("paper") or {}).get("status") or "n/a").upper(),
        )

    rows = scan_result.get("results")
    rows = rows if isinstance(rows, list) else []
    if rows:
        frame = pd.DataFrame(rows)
        preferred = [
            "symbol",
            "signal",
            "score",
            "confidence",
            "trigger",
            "entry",
            "stoploss",
            "target2",
            "reward_risk",
            "bar_at",
            "error",
        ]
        columns = [column for column in preferred if column in frame.columns]
        st.dataframe(
            frame[columns] if columns else frame,
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("Technical evidence and provider attribution"):
        st.json(
            {
                "top_picks": scan_result.get("top_picks") or [],
                "paper": scan_result.get("paper") or {},
                "provider_observation": (
                    scan_result.get("provider_observation") or {}
                ),
                "safety": scan_result.get("safety") or {},
            }
        )

st.divider()
st.subheader("Technical backtest")

backtest_mode = st.radio(
    "Backtest style",
    ["swing", "intraday"],
    horizontal=True,
    format_func=lambda value: value.title(),
    key="tf_technical_backtest_mode",
)
backtest_periods = (
    ["30d", "45d", "60d"]
    if backtest_mode == "intraday"
    else ["1y", "2y", "5y"]
)
backtest_period_index = 2 if backtest_mode == "intraday" else 1

with st.form("technical_backtest_form"):
    a, b, c = st.columns(3)
    with a:
        bt_symbol = st.text_input(
            "Backtest symbol",
            value="RELIANCE",
            max_chars=30,
        )
    with b:
        bt_period = st.selectbox(
            "Backtest history",
            backtest_periods,
            index=backtest_period_index,
        )
    with c:
        capital = st.number_input(
            "Initial capital (₹)",
            min_value=1_000.0,
            max_value=1_000_000_000.0,
            value=100_000.0,
            step=10_000.0,
        )

    d, e = st.columns(2)
    with d:
        cost_bps = st.number_input(
            "Transaction cost (bps/side)",
            min_value=0.0,
            max_value=1_000.0,
            value=0.0,
            step=1.0,
        )
    with e:
        slippage_bps = st.number_input(
            "Slippage (bps/side)",
            min_value=0.0,
            max_value=1_000.0,
            value=0.0,
            step=1.0,
        )

    bt_submit = st.form_submit_button(
        "Run technical backtest",
        type="primary",
        use_container_width=True,
    )

if bt_submit:
    if not bt_symbol.strip():
        st.error("Enter a symbol.")
    elif not admin_key_configured():
        st.error("Configure the production admin key first.")
    else:
        run_id = f"ui-tech-bt-{uuid4().hex[:16]}"
        try:
            with st.spinner(
                f"Backtesting {bt_symbol.strip().upper()} "
                f"({backtest_mode}, {bt_period})..."
            ):
                result = client.post_json(
                    "/technical/backtest",
                    {
                        "symbol": bt_symbol.strip().upper(),
                        "mode": backtest_mode,
                        "period": bt_period,
                        "capital": float(capital),
                        "cost_bps": float(cost_bps),
                        "slippage_bps": float(slippage_bps),
                        "run_id": run_id,
                    },
                    timeout=240,
                )
            st.session_state["tf_technical_backtest_result"] = result
            st.success(
                f"Backtest completed: {result.get('run_id', run_id)}"
            )
        except ApiError as exc:
            render_api_error(exc, title="Technical backtest failed")

bt_result = st.session_state.get("tf_technical_backtest_result")
if isinstance(bt_result, dict):
    metrics = bt_result.get("metrics") or {}
    a, b, c, d, e = st.columns(5)
    with a:
        st.metric("Trades", int(metrics.get("total_trades") or 0))
    with b:
        st.metric(
            "Return",
            f"{float(metrics.get('return_pct') or 0.0):.2f}%",
        )
    with c:
        st.metric(
            "Win rate",
            f"{float(metrics.get('win_rate') or 0.0):.2f}%",
        )
    with d:
        st.metric(
            "Max DD",
            f"{float(metrics.get('max_drawdown_pct') or 0.0):.2f}%",
        )
    with e:
        st.metric(
            "Profit factor",
            str(metrics.get("profit_factor")),
        )

    trades = bt_result.get("trades")
    trades = trades if isinstance(trades, list) else []
    if trades:
        st.dataframe(
            pd.DataFrame(trades),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No completed trades were generated for this window.")

    with st.expander("Backtest provenance"):
        st.json(
            {
                "strategy": bt_result.get("strategy") or {},
                "engine": bt_result.get("engine") or {},
                "parameters": bt_result.get("parameters") or {},
                "provider_observation": (
                    bt_result.get("provider_observation") or {}
                ),
                "safety": bt_result.get("safety") or {},
            }
        )
