"""Weekend Research: research-only scanner and reproducible historical backtests."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from services.weekend_research_service import (
    MAX_SYMBOLS, STRATEGY, backtest_symbol, last_completed_date,
    normalize_symbol, parse_csv, prepare_frame, rank_candidates,
)
from webapp.ui import page_header, info_note

page_header(
    "Weekend Research & Stock Selection",
    "Research completed NSE daily candles on weekends and after market close. "
    "Screen ranked candidates and backtest with next-bar-open simulated fills.",
    kicker="Research",
)
info_note(
    "Research only — no Kite login, paper trades or live orders. "
    "Historical candles, not live LTP. Prices and selections are date-stamped. "
    "Public data can be delayed or unavailable."
)

st.caption(
    f"Latest eligible regular-session candle: {last_completed_date().date()} (IST). "
    "Holiday and special-session schedules are not verified in this standalone page."
)

with st.expander("How to use it / data limitations"):
    st.write(
        "Select a historical source and press **Load & rank**. "
        "On weekends this analyzes the previous completed trading session. "
        "A BUY_CROSS is a completed-bar research signal, **not an executable buy order**. "
        "TREND_WATCH is a trend candidate without a new crossover. "
        "No future bars are allowed. A signal on Friday close cannot be filled before "
        "the next available session's open."
    )
    st.write(
        "Yahoo data, when available, is adjusted for corporate actions; fills are "
        "hypothetical, not actual historical execution prices. CSV inputs should "
        "contain appropriately corporate-action-adjusted daily candles. "
        "Results exclude realistic market impact, borrow constraints, taxes, "
        "intraday stops, holidays and survivorship bias."
    )

source = st.radio(
    "Candle source",
    ["Public Yahoo daily history (best effort)", "Upload OHLCV CSV (offline)"],
    horizontal=True,
)
uploaded = None
symbols_text = ""
lookback = "2y"
if source.startswith("Upload"):
    uploaded = st.file_uploader("Upload CSV (max 8 MB)", type=["csv"])
    st.caption("Required columns: Date, Symbol, Open, High, Low, Close, Volume — multiple symbols in one CSV.")
    template = "Date,Symbol,Open,High,Low,Close,Volume\n"
    st.download_button("Download CSV header", template, file_name="trendforge_ohlcv_template.csv",
                       mime="text/csv")
else:
    symbols_text = st.text_input(
        "NSE symbols (comma-separated, maximum 20)",
        value="BSE,CAMS,COFORGE,FORCEMOT,JYOTICNC,LUPIN,MCX,POWERINDIA,SUZLON",
    )
    lookback = st.selectbox("Daily history lookback", ["1y", "2y", "5y"], index=1)
    st.caption("Data supplied by Yahoo Finance, if reachable. Not from Zerodha, not a real-time feed.")

c1, c2, c3 = st.columns(3)
with c1:
    rsi_min = st.slider("Minimum RSI14", 40, 80, 60)
with c2:
    proximity = st.slider("Maximum EMA20 distance (%)", 0.5, 5.0, 1.0, step=0.5)
with c3:
    volume_filter = st.checkbox("Volume > 20-day average", value=True)


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_public_history(symbol: str, period: str) -> pd.DataFrame:
    # Network is triggered only by the operator's explicit Load & rank action.
    import yfinance as yf
    raw = yf.download(
        f"{symbol}.NS", period=period, interval="1d",
        auto_adjust=True, progress=False, threads=False, timeout=15,
    )
    if raw is None or raw.empty:
        raise ValueError("No public daily candles returned")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    frame = raw.rename(columns={key: key.lower() for key in raw.columns})
    return prepare_frame(frame, symbol=symbol)


def fetch_public_symbols(names: list[str], period: str):
    history, errors = {}, {}
    for symbol in names:
        try:
            history[symbol] = fetch_public_history(symbol, period)
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: public history unavailable"
    return history, errors


run = st.button("Load & rank completed daily candles", type="primary",
                use_container_width=True)
if run:
    try:
        failures = {}
        if source.startswith("Upload"):
            if uploaded is None:
                raise ValueError("Choose a CSV file first")
            history = parse_csv(uploaded.getvalue())
            basis = "Uploaded CSV (user-provided daily prices)"
        else:
            selected = [normalize_symbol(item) for item in symbols_text.split(",") if item.strip()]
            if not selected or len(set(selected)) > MAX_SYMBOLS:
                raise ValueError("Provide 1 to 20 unique NSE symbols")
            selected = list(dict.fromkeys(selected))
            history, failures = fetch_public_symbols(selected, lookback)
            basis = "Yahoo adjusted historical daily prices (best effort)"
        if not history:
            raise ValueError("No valid historical candles available")
        ranked, skipped = rank_candidates(
            history, rsi_min=float(rsi_min),
            proximity_pct=float(proximity), volume_filter=volume_filter,
        )
        failures.update(skipped)
        st.session_state.pop("tf_weekend_backtest_result", None)
        st.session_state["tf_weekend_research"] = {
            "history": history, "ranked": ranked, "errors": failures,
            "basis": basis, "params": {
                "rsi_min": float(rsi_min), "proximity": float(proximity),
                "volume_filter": bool(volume_filter),
            },
        }
    except Exception as exc:
        st.error(f"Research was not started: {exc}")

state = st.session_state.get("tf_weekend_research")
if state:
    ranked = state["ranked"]
    st.divider()
    st.subheader("Weekend stock selections — completed candles")
    st.caption(
        f"Source: {state['basis']} · Strategy: {STRATEGY} · "
        "Ranking is analysis only. A stale stock never gets an active entry flag."
    )
    if state["errors"]:
        with st.expander(f"{len(state['errors'])} symbol(s) skipped", expanded=False):
            st.json(state["errors"])
    if ranked.empty:
        st.warning("No symbols passed the historical data checks.")
    else:
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Analyzed stocks", len(ranked))
        with m2:
            st.metric("New BUY_CROSS research signals", int(ranked["Entry signal"].sum()))
        with m3:
            st.metric("Trend watch candidates", int((ranked["Classification"] == "TREND_WATCH").sum()))
        st.dataframe(ranked, use_container_width=True, hide_index=True)
        st.download_button(
            "Download ranked stock selection CSV",
            ranked.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"trendforge_weekend_selections_{last_completed_date().date()}.csv",
            mime="text/csv",
        )

        st.divider()
        st.subheader("Historical backtesting engine")
        st.caption(
            "Canonical TrendForge next-open long-only simulator; transaction costs "
            "and slippage apply to both entry and exit. Results are hypothetical."
        )
        choices = ranked["Symbol"].tolist()
        with st.form("weekend_backtest"):
            a, b, c = st.columns(3)
            with a:
                selected_symbol = st.selectbox("Backtest stock", choices)
            with b:
                capital = st.number_input("Capital (₹)", min_value=1000.0,
                    max_value=1e8, value=100000.0, step=10000.0)
            with c:
                cost_bps = st.number_input("Cost (bps per side)", 0.0, 1000.0, 10.0, step=1.0)
            slippage_bps = st.number_input(
                "Slippage (bps per side)", 0.0, 1000.0, 10.0, step=1.0
            )
            submit_bt = st.form_submit_button("Run historical backtest", type="primary")
        if submit_bt:
            try:
                result = backtest_symbol(
                    selected_symbol, state["history"][selected_symbol],
                    initial_capital=capital, cost_bps=cost_bps, slippage_bps=slippage_bps,
                    rsi_min=state["params"]["rsi_min"],
                    proximity_pct=state["params"]["proximity"],
                    volume_filter=state["params"]["volume_filter"],
                )
                st.session_state["tf_weekend_backtest_result"] = result
            except Exception as exc:
                st.error(f"Backtest failed: {exc}")

        result = st.session_state.get("tf_weekend_backtest_result")
        if result and result["symbol"] in state["history"]:
            st.caption(
                f"Backtest: {result['symbol']} · through {result['as_of']} · "
                f"{result['execution']} · price source: {state['basis']}"
            )
            metrics = result["metrics"]
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Net profit (₹)", f"{metrics.get('net_profit', 0):,.2f}")
            k2.metric("Return", f"{metrics.get('return_pct', 0):.2f}%")
            k3.metric("Win rate", f"{metrics.get('win_rate', 0):.2f}%")
            k4.metric("Completed trades", metrics.get("total_trades", 0))
            curve = pd.DataFrame(result["equity_curve"])
            if not curve.empty:
                st.line_chart(curve.set_index("date")["equity"])
            st.dataframe(pd.DataFrame(result["trades"]), use_container_width=True,
                         hide_index=True)
            st.download_button(
                "Download backtest trades CSV",
                pd.DataFrame(result["trades"]).to_csv(index=False).encode("utf-8-sig"),
                file_name=f"trendforge_{result['symbol']}_backtest.csv",
                mime="text/csv",
            )
