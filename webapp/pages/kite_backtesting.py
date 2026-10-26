"""Historical backtests based exclusively on Kite OHLCV candles."""
from __future__ import annotations

from uuid import uuid4

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.backtest_pnl import render_backtest_pnl
from webapp.trade_timestamps import format_trade_frame, export_trade_frame
from webapp.paper_excel import safe_csv_bytes
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import page_header, render_api_error
from webapp.nifty_selection import select_nifty_stocks
from scanner.workspace_strategies import strategy_choices

page_header(
    "Kite Historical Backtesting",
    "Evaluate intraday or swing technical setups on historical Kite candles with explicit costs and slippage.",
    kicker="03 / Backtesting",
)
from webapp.strategy_catalog import clear_retired_scan_cache
clear_retired_scan_cache()
client = api_client(timeout=240)
try:
    readiness = client.get_json("/technical/readiness")
except ApiError as exc:
    render_api_error(exc, title="Kite technical history unavailable")
    st.stop()

st.caption("Backtests are simulations only. No paper positions or live broker orders are created. Costs and slippage can materially affect results.")
mode = st.radio("Backtest timeframe", ["swing", "intraday", "positional"], horizontal=True, format_func=lambda value: "Medium / Long term" if value == "positional" else value.title())
source = st.radio(
    "Backtest source", ["Single stock", "Scanner matches"], horizontal=True,
)
if source == "Scanner matches":
    from webapp.scanner_backtesting import render_scanner_backtests

    render_scanner_backtests(client, mode=mode, authorized=admin_key_configured())
    st.stop()
choices = strategy_choices(mode)
strategy_label = st.selectbox("Scanner / strategy", list(choices))
strategy_id = choices[strategy_label]
if mode == "positional":
    from webapp.strategy_catalog import render_review_scanner
    render_review_scanner(client, strategy_id, key="kite_backtesting_review")
    st.stop()
selection = select_nifty_stocks(client, key="single_backtest", single=True)
symbol = selection["symbols"][0] if selection["symbols"] else ""
with st.form("tf_r726_kite_backtest"):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.caption("Selected NSE stock")
        st.write(symbol or "List unavailable")
    with c2:
        period = st.selectbox("Kite OHLCV history", ["1y", "2y", "5y"] if mode == "swing" else ["30d", "45d", "60d"], index=1 if mode == "swing" else 2)
    with c3:
        capital = st.number_input("Initial capital (₹)", min_value=1000.0, max_value=1e9, value=100000.0, step=10000.0)
    d1, d2 = st.columns(2)
    with d1:
        cost_bps = st.number_input("Transaction cost (basis points per side)", min_value=0.0, max_value=1000.0, value=12.0)
    with d2:
        slippage_bps = st.number_input("Slippage (basis points per side)", min_value=0.0, max_value=1000.0, value=5.0)
    submitted = st.form_submit_button("Run Kite backtest", type="primary", disabled=not admin_key_configured())

if submitted:
    st.session_state.pop("tf_r726_backtest_result", None)
    if not symbol:
        st.error("A valid NSE symbol is required.")
    else:
        try:
            response = client.post_json(
                "/technical/backtest",
                {
                    "symbol": symbol, "mode": mode, "period": period, "strategy_id": strategy_id,
                    "capital": float(capital), "cost_bps": float(cost_bps),
                    "slippage_bps": float(slippage_bps),
                    "run_id": f"tf-r726-bt-{uuid4().hex[:12]}",
                },
                timeout=240,
            )
            if (
                response.get("status") != "completed"
                or not isinstance(response.get("metrics"), dict)
                or not isinstance(response.get("trades"), list)
                or not all(isinstance(row, dict) for row in response["trades"])
            ):
                raise ApiError("The backend returned an invalid historical backtest result")
            st.session_state["tf_r726_backtest_result"] = response
        except ApiError as exc:
            render_api_error(exc, title="Historical Kite backtest failed")

if not admin_key_configured():
    st.info("The Admin API Key is required to run historical backtests.")

result = st.session_state.get("tf_r726_backtest_result")
if isinstance(result, dict):
    if result.get("symbol") and result.get("period"):
        st.caption(f"Displayed result: {result['symbol']} · {result['period']}")
    metrics = result.get("metrics") or {}
    a, b, c, d, e = st.columns(5)
    a.metric("Trades", int(metrics.get("total_trades") or 0))
    b.metric("Return", f"{float(metrics.get('return_pct') or 0):.2f}%")
    c.metric("Win rate", f"{float(metrics.get('win_rate') or 0):.2f}%")
    d.metric("Max drawdown", f"{float(metrics.get('max_drawdown_pct') or 0):.2f}%")
    factor = metrics.get("profit_factor")
    e.metric("Profit factor", "—" if factor is None else str(factor))
    render_backtest_pnl([result], key="single_backtest_pnl")
    trades = result.get("trades") or []
    if isinstance(trades, list) and trades:
        frame = pd.DataFrame(trades)
        st.subheader("Historical trade ledger")
        st.dataframe(format_trade_frame(frame, daily=result.get("interval") == "1d"), use_container_width=True, hide_index=True)
        st.download_button("Export backtest trades (CSV)", safe_csv_bytes(export_trade_frame(frame, daily=result.get("interval") == "1d")), file_name="trendforge_kite_backtest.csv", mime="text/csv")
    else:
        st.info("The selected history yielded no closed trades.")
    with st.expander("Engine parameters and data evidence"):
        st.json({k: result.get(k) for k in ("strategy", "engine", "parameters", "provider_observation", "safety")})
