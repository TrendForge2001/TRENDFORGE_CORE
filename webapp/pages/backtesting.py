"""Historical strategy backtesting dashboard."""
from __future__ import annotations

from uuid import uuid4

import pandas as pd

from webapp.paper_excel import safe_csv_bytes

from webapp.trade_timestamps import format_trade_frame
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Backtesting",
    "Test the versioned EMA20/EMA50 + RSI strategy on historical daily data with next-bar execution, configurable costs, persisted runs, benchmark comparison, and full trade evidence.",
    kicker="Research",
)

client = api_client(timeout=180)

try:
    readiness = client.get_json("/backtests/readiness")
except ApiError as exc:
    render_api_error(
        exc,
        title="Backtesting service unavailable",
    )
    st.stop()

info_note(
    "Historical simulation only. A signal is calculated after a daily bar closes and can fill only at the next bar's open. Backtests never create paper or broker orders."
)

r1, r2, r3, r4 = st.columns(4)
with r1:
    st.metric(
        "Strategy",
        str(readiness.get("strategy") or "unknown"),
    )
with r2:
    st.metric(
        "Version",
        str(readiness.get("strategy_version") or "unknown"),
    )
with r3:
    st.metric(
        "Execution",
        "NEXT OPEN",
    )
with r4:
    st.metric(
        "Persisted runs",
        int(readiness.get("persisted_runs") or 0),
    )

if readiness.get("broker_orders_allowed"):
    st.error(
        "Unexpected safety state: backtesting reports broker orders enabled."
    )

with st.form("run_backtest"):
    a, b, c, d = st.columns(4)
    with a:
        symbol = st.text_input(
            "Symbol",
            value="TCS",
            max_chars=30,
        )
    with b:
        period = st.selectbox(
            "History",
            ["1y", "2y", "5y"],
            index=1,
        )
    with c:
        capital = st.number_input(
            "Initial capital (₹)",
            min_value=1_000.0,
            max_value=1_000_000_000.0,
            value=100_000.0,
            step=10_000.0,
        )
    with d:
        rsi_threshold = st.number_input(
            "RSI threshold",
            min_value=0.0,
            max_value=100.0,
            value=60.0,
            step=1.0,
        )

    e, f, g = st.columns(3)
    with e:
        proximity = st.number_input(
            "EMA20 proximity (%)",
            min_value=0.0,
            max_value=20.0,
            value=1.0,
            step=0.1,
            help=(
                "Entry crossover is accepted only when close is within "
                "this percentage of EMA20."
            ),
        )
    with f:
        cost_bps = st.number_input(
            "Transaction cost (bps/side)",
            min_value=0.0,
            max_value=1_000.0,
            value=0.0,
            step=1.0,
        )
    with g:
        slippage_bps = st.number_input(
            "Slippage (bps/side)",
            min_value=0.0,
            max_value=1_000.0,
            value=0.0,
            step=1.0,
        )

    submitted = st.form_submit_button(
        "Run backtest",
        type="primary",
        use_container_width=True,
    )

if submitted:
    if not admin_key_configured():
        st.error(
            "Configure the production admin key before running a backtest."
        )
    elif not symbol.strip():
        st.error("Enter a symbol.")
    else:
        run_id = f"ui-bt-{uuid4().hex}"
        try:
            with st.spinner(
                f"Backtesting {symbol.strip().upper()} over {period}..."
            ):
                result = client.post_json(
                    "/backtests",
                    {
                        "symbol": symbol.strip().upper(),
                        "period": period,
                        "interval": "1d",
                        "capital": float(capital),
                        "rsi_threshold": float(
                            rsi_threshold
                        ),
                        "ema_proximity_pct": float(
                            proximity
                        ),
                        "cost_bps": float(cost_bps),
                        "slippage_bps": float(
                            slippage_bps
                        ),
                        "run_id": run_id,
                    },
                    timeout=180,
                )
            st.session_state[
                "tf_backtest_result"
            ] = result
            st.success(
                f"Backtest completed: {result.get('run_id', run_id)}"
            )
        except ApiError as exc:
            render_api_error(
                exc,
                title="Backtest failed",
            )

try:
    history = client.get_json(
        "/backtests",
        params={"limit": 100},
    )
except ApiError as exc:
    render_api_error(
        exc,
        title="Backtest history unavailable",
    )
    history = {"runs": []}

history_rows = history.get("runs")
history_rows = (
    history_rows
    if isinstance(history_rows, list)
    else []
)

st.divider()
st.subheader("Persisted runs")

if history_rows:
    history_frame = pd.DataFrame(history_rows)
    preferred = [
        "run_id",
        "symbol",
        "strategy_version",
        "start_date",
        "end_date",
        "total_trades",
        "win_rate",
        "net_profit",
        "return_pct",
        "buy_hold_return_pct",
        "max_drawdown",
        "sharpe_ratio",
        "profit_factor",
        "created_at",
    ]
    columns = [
        column
        for column in preferred
        if column in history_frame.columns
    ]
    st.dataframe(
        format_trade_frame(history_frame[columns]),
        use_container_width=True,
        hide_index=True,
    )

    run_ids = [
        str(row.get("run_id"))
        for row in history_rows
        if row.get("run_id")
    ]
    selected_run = st.selectbox(
        "Inspect persisted run",
        run_ids,
    )
    if st.button(
        "Load run detail",
        use_container_width=True,
    ):
        try:
            st.session_state[
                "tf_backtest_result"
            ] = client.get_json(
                f"/backtests/{selected_run}"
            )
            st.rerun()
        except ApiError as exc:
            render_api_error(
                exc,
                title="Backtest detail unavailable",
            )
else:
    st.info("No R68.4 backtest runs have been persisted yet.")

result = st.session_state.get("tf_backtest_result")
if not isinstance(result, dict) or not result:
    st.stop()

st.divider()
st.subheader(
    f"Run detail · {result.get('symbol', '—')} · "
    f"{result.get('run_id', '—')}"
)

metrics = result.get("metrics")
metrics = metrics if isinstance(metrics, dict) else {}

m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.metric(
        "Return",
        f"{float(metrics.get('return_pct') or 0):.2f}%",
    )
with m2:
    st.metric(
        "Buy & hold",
        f"{float(metrics.get('buy_hold_return_pct') or 0):.2f}%",
    )
with m3:
    st.metric(
        "Net P&L",
        f"₹{float(metrics.get('net_profit') or 0):,.0f}",
    )
with m4:
    st.metric(
        "Trades",
        int(metrics.get("total_trades") or 0),
    )
with m5:
    st.metric(
        "Win rate",
        f"{float(metrics.get('win_rate') or 0):.1f}%",
    )
with m6:
    st.metric(
        "Max drawdown",
        f"{float(metrics.get('max_drawdown_pct') or 0):.2f}%",
    )

q1, q2, q3, q4, q5 = st.columns(5)
with q1:
    st.metric(
        "Final capital",
        f"₹{float(metrics.get('final_capital') or 0):,.0f}",
    )
with q2:
    profit_factor = metrics.get("profit_factor")
    st.metric(
        "Profit factor",
        (
            "∞"
            if profit_factor is None
            and float(metrics.get("net_profit") or 0) > 0
            else f"{float(profit_factor or 0):.2f}"
        ),
    )
with q3:
    st.metric(
        "Expectancy",
        f"₹{float(metrics.get('expectancy') or 0):,.0f}",
    )
with q4:
    st.metric(
        "Sharpe",
        f"{float(metrics.get('sharpe_ratio') or 0):.2f}",
    )
with q5:
    st.metric(
        "Exposure",
        f"{float(metrics.get('exposure_pct') or 0):.1f}%",
    )

benchmark = pd.DataFrame(
    {
        "Return %": [
            float(metrics.get("return_pct") or 0),
            float(
                metrics.get(
                    "buy_hold_return_pct"
                )
                or 0
            ),
        ]
    },
    index=["Strategy", "Buy & Hold"],
)
st.subheader("Strategy vs benchmark")
st.bar_chart(benchmark)

equity = result.get("equity_curve")
equity = equity if isinstance(equity, list) else []
if equity:
    st.subheader("Equity curve")
    equity_frame = pd.DataFrame(equity)
    if {"date", "equity"} <= set(equity_frame.columns):
        equity_frame["date"] = pd.to_datetime(
            equity_frame["date"],
            errors="coerce",
        )
        equity_frame = (
            equity_frame
            .dropna(subset=["date"])
            .set_index("date")
        )
        st.line_chart(
            equity_frame[["equity"]]
        )

trades = result.get("trades")
trades = trades if isinstance(trades, list) else []
st.subheader("Trade ledger")
if trades:
    trades_frame = pd.DataFrame(trades)
    st.dataframe(
        format_trade_frame(trades_frame),
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Download trades CSV",
        data=safe_csv_bytes(trades_frame),
        file_name=(
            f"trendforge_{result.get('symbol', 'symbol')}_"
            f"{result.get('run_id', 'backtest')}_trades.csv"
        ),
        mime="text/csv",
    )
else:
    st.info(
        "No completed trades matched this strategy and parameter set."
    )

with st.expander("Strategy & parameters"):
    st.json(
        {
            "strategy": result.get("strategy"),
            "parameters": result.get("parameters"),
            "period": result.get("period"),
            "interval": result.get("interval"),
            "bars": result.get("bars"),
            "start_date": result.get("start_date"),
            "end_date": result.get("end_date"),
        }
    )

with st.expander("Costs, provider evidence & safety"):
    st.json(
        {
            "transaction_costs": metrics.get(
                "transaction_costs"
            ),
            "slippage_impact_estimate": metrics.get(
                "slippage_impact_estimate"
            ),
            "provider_observation": result.get(
                "provider_observation"
            ),
            "safety": result.get("safety"),
        }
    )
