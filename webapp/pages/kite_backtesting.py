"""Historical backtests based exclusively on Kite OHLCV candles."""
from __future__ import annotations

from uuid import uuid4

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import page_header, render_api_error

page_header(
    "Kite Historical Backtesting",
    "Evaluate intraday or swing technical setups on historical Kite candles with explicit costs and slippage.",
    kicker="03 / Backtesting",
)
client = api_client(timeout=240)
try:
    readiness = client.get_json("/technical/readiness")
except ApiError as exc:
    render_api_error(exc, title="Kite technical history unavailable")
    st.stop()

st.caption("Backtests are simulations only. No paper positions or live broker orders are created. Costs and slippage can materially affect results.")
with st.form("tf_r726_kite_backtest"):
    mode = st.radio("Backtest timeframe", ["swing", "intraday"], horizontal=True, format_func=str.title)
    c1, c2, c3 = st.columns(3)
    with c1:
        symbol = st.text_input("NSE symbol", value="RELIANCE", max_chars=30).strip().upper()
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
    if not symbol:
        st.error("A valid NSE symbol is required.")
    else:
        try:
            response = client.post_json(
                "/technical/backtest",
                {
                    "symbol": symbol, "mode": mode, "period": period,
                    "capital": float(capital), "cost_bps": float(cost_bps),
                    "slippage_bps": float(slippage_bps),
                    "run_id": f"tf-r726-bt-{uuid4().hex[:12]}",
                },
                timeout=240,
            )
            st.session_state["tf_r726_backtest_result"] = response
        except ApiError as exc:
            render_api_error(exc, title="Historical Kite backtest failed")

if not admin_key_configured():
    st.info("The Admin API Key is required to run historical backtests.")

result = st.session_state.get("tf_r726_backtest_result")
if isinstance(result, dict):
    metrics = result.get("metrics") or {}
    a, b, c, d, e = st.columns(5)
    a.metric("Trades", int(metrics.get("total_trades") or 0))
    b.metric("Return", f"{float(metrics.get('return_pct') or 0):.2f}%")
    c.metric("Win rate", f"{float(metrics.get('win_rate') or 0):.2f}%")
    d.metric("Max drawdown", f"{float(metrics.get('max_drawdown_pct') or 0):.2f}%")
    e.metric("Profit factor", str(metrics.get("profit_factor") or "—"))
    trades = result.get("trades") or []
    if isinstance(trades, list) and trades:
        frame = pd.DataFrame(trades)
        st.subheader("Historical trade ledger")
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.download_button("Export backtest trades (CSV)", frame.to_csv(index=False).encode("utf-8-sig"), file_name="trendforge_kite_backtest.csv", mime="text/csv")
    else:
        st.info("The selected history yielded no closed trades.")
    with st.expander("Engine parameters and data evidence"):
        st.json({k: result.get(k) for k in ("strategy", "engine", "parameters", "provider_observation", "safety")})
