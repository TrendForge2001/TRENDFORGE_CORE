"""Shared-account backtesting controls and portfolio P&L in the existing tab."""

from contextlib import nullcontext
from uuid import uuid4

import pandas as pd
import streamlit as st

from scanner.portfolio_policy import number
from scanner.technical_strategy import strategy_profile
from scanner.workspace_strategies import strategy_choices
from webapp.api_client import ApiError
from webapp.candidate_analysis import render_candidate_analysis
from webapp.nifty_selection import scan_nifty_stocks, select_nifty_stocks
from webapp.paper_excel import safe_csv_bytes
from webapp.scanner_backtesting import matching_rows, scanner_description
from webapp.trade_timestamps import (
    export_trade_frame,
    format_trade_frame,
    market_timestamp,
)
from webapp.ui import render_api_error
from webapp.workspace_layout import workspace_panels

RESULT_KEY = "tf_r726_backtest_result"


def validate_result(result: dict) -> None:
    metrics = result.get("metrics")
    parameters = result.get("parameters")
    trades, curve = result.get("trades"), result.get("equity_curve")
    if (
        result.get("status") != "completed"
        or not isinstance(metrics, dict)
        or not isinstance(parameters, dict)
        or not isinstance(trades, list)
        or not all(isinstance(row, dict) for row in trades)
        or not isinstance(curve, list)
        or not curve
        or metrics.get("initial_capital") != 100000
        or parameters.get("deployment_limit") != 80000
        or parameters.get("cash_reserve") != 20000
        or parameters.get("max_positions") != 3
    ):
        raise ApiError("The backend returned an invalid shared-portfolio result")
    final, net = number(metrics.get("final_capital")), number(metrics.get("net_profit"))
    if final is None or net is None or abs(final - net - 100000) > 0.02:
        raise ApiError("Portfolio capital does not reconcile")
    if any(number(metrics.get(k)) is None for k in ("return_pct", "max_drawdown_pct")):
        raise ApiError("Portfolio return/drawdown evidence is incomplete")
    pnls = [number(row.get("net_pnl")) for row in trades]
    if (
        None in pnls
        or len(trades) != metrics.get("total_trades")
        or abs(sum(pnls) - net) > 0.02 + len(trades) * 0.01
    ):
        raise ApiError("Portfolio trade P&L does not reconcile")
    for trade in trades:
        entry, exit_at = (
            market_timestamp(trade.get("entry_at")),
            market_timestamp(trade.get("exit_at")),
        )
        if (
            not isinstance(trade.get("symbol"), str)
            or not trade["symbol"]
            or type(trade.get("quantity")) is not int
            or trade["quantity"] <= 0
            or entry is None
            or exit_at is None
            or exit_at < entry
            or number(trade.get("transaction_costs")) is None
        ):
            raise ApiError("Portfolio trade evidence is incomplete")
    for point in curve:
        if not isinstance(point, dict):
            raise ApiError("Invalid portfolio equity observations")
        cash = number(point.get("cash"))
        equity = number(point.get("equity"))
        deployed = number(point.get("capital_committed"))
        count = point.get("open_positions")
        if (
            cash is None
            or equity is None
            or market_timestamp(point.get("date")) is None
            or cash < 20000
            or deployed is None
            or not 0 <= deployed <= 80000
            or type(count) is not int
            or not 0 <= count <= 3
        ):
            raise ApiError("Portfolio capital limits do not reconcile")
    if abs(number(curve[-1]["equity"]) - final) > 0.02:
        raise ApiError("Portfolio equity does not reconcile")


def _download(controls, *args, **kwargs):
    with controls if controls is not None else nullcontext():
        return st.download_button(*args, **kwargs)


def render_result(result: dict, *, controls=None) -> None:
    metrics = result["metrics"]
    with controls if controls is not None else nullcontext():
        view = st.selectbox(
            "Backtest result view",
            ["Summary", "Stock P&L", "Daily P&L", "Trades", "Equity", "Run details"],
            key="portfolio_result_view",
        )
    st.subheader("Backtesting P&L dashboard")
    st.caption(
        f"{result.get('strategy_id', '—')} · {result.get('mode', '—')} · "
        f"{result.get('period', '—')}"
    )
    a, b, c, d = st.columns(4)
    a.metric("Net P&L", f"₹{metrics['net_profit']:,.2f}")
    b.metric("Account return", f"{metrics.get('return_pct', 0):.2f}%")
    c.metric("Ending capital", f"₹{metrics['final_capital']:,.2f}")
    d.metric("Max drawdown", f"{metrics.get('max_drawdown_pct', 0):.2f}%")
    equity = pd.DataFrame(result["equity_curve"])
    trades = pd.DataFrame(result["trades"])
    if view == "Summary":
        a, b, c, d = st.columns(4)
        a.metric("Trades", metrics["total_trades"])
        b.metric(
            "Profit factor",
            "—"
            if metrics.get("profit_factor") is None
            else str(metrics["profit_factor"]),
        )
        c.metric("Max concurrent stocks", metrics.get("max_observed_positions", 0))
        d.metric("Lowest cash balance", f"₹{metrics.get('minimum_cash', 100000):,.2f}")
        st.caption(
            "Shared ₹1,00,000 account · ₹80,000 maximum collateral · "
            "₹20,000 reserve · at most 3 stocks. "
            "Net P&L includes configured fees and fill slippage."
        )
        st.line_chart(equity.set_index("date")[["equity", "cash"]], height=230)
    elif view == "Equity":
        st.line_chart(equity.set_index("date")[["equity", "cash"]], height=330)
        _download(
            controls,
            "Export portfolio equity (CSV)",
            safe_csv_bytes(equity),
            "trendforge_portfolio_equity.csv",
            "text/csv",
        )
    elif view == "Run details":
        st.json(
            {
                key: result.get(key)
                for key in (
                    "symbols",
                    "strategy",
                    "parameters",
                    "metrics",
                    "safety",
                    "start_date",
                    "end_date",
                )
            }
        )
    elif trades.empty:
        st.info("No historical entry setups passed; capital stayed in cash.")
    elif view == "Stock P&L":
        summary = trades.groupby("symbol", as_index=False).agg(
            trades=("net_pnl", "size"),
            net_pnl=("net_pnl", "sum"),
            transaction_costs=("transaction_costs", "sum"),
        )
        st.dataframe(summary, hide_index=True, use_container_width=True)
        _download(
            controls,
            "Export stock P&L (CSV)",
            safe_csv_bytes(summary),
            "trendforge_portfolio_stock_pnl.csv",
            "text/csv",
        )
    elif view == "Daily P&L":
        daily = trades.copy()
        daily["exit_day_ist"] = (
            pd.to_datetime(daily["exit_at"], utc=True)
            .dt.tz_convert("Asia/Kolkata")
            .dt.date.astype(str)
        )
        daily = daily.groupby("exit_day_ist", as_index=False)["net_pnl"].sum()
        st.bar_chart(daily.set_index("exit_day_ist"), height=280)
        _download(
            controls,
            "Export daily P&L (CSV)",
            safe_csv_bytes(daily),
            "trendforge_portfolio_daily_pnl.csv",
            "text/csv",
        )
    elif view == "Trades":
        flattened = [
            {
                **{
                    k: v
                    for k, v in trade.items()
                    if k not in {"indicators", "technical_evidence"}
                },
                **{f"indicator_{k}": v for k, v in trade.get("indicators", {}).items()},
            }
            for trade in result["trades"]
        ]
        ledger = pd.DataFrame(flattened)
        daily_bars = result.get("interval") == "1d"
        st.dataframe(
            format_trade_frame(ledger, daily=daily_bars),
            hide_index=True,
            use_container_width=True,
        )
        _download(
            controls,
            "Export portfolio trades (CSV)",
            safe_csv_bytes(export_trade_frame(ledger, daily=daily_bars)),
            "trendforge_portfolio_trades.csv",
            "text/csv",
        )


def render_portfolio_backtesting(client, *, authorized: bool) -> None:
    controls, results_panel = workspace_panels("backtest")
    with controls:
        mode = st.radio(
            "Backtest timeframe",
            ["swing", "intraday", "positional"],
            horizontal=True,
            format_func=lambda x: "Position" if x == "positional" else x.title(),
        )
        source = st.radio(
            "Backtest source",
            ["Nifty list / sector", "Scanner matches"],
            horizontal=True,
        )
        choices = strategy_choices(mode)
        label = st.selectbox("Scanner / strategy", list(choices))
        strategy_id = choices[label]
        if mode == "positional":
            from webapp.strategy_catalog import render_review_scanner

            render_review_scanner(
                client, strategy_id, key="portfolio_review", results=results_panel
            )
            return
        profile = scanner_description(mode, strategy_id)
        st.caption("Indicators applied: " + profile["indicators"])
        with st.expander("View conditions and indicators"):
            st.write(profile["conditions"])
        a, b = st.columns(2)
        c, d = st.columns(2)
        a.metric("Total capital", "₹1,00,000")
        b.metric("Trading budget", "₹80,000")
        c.metric("Cash reserve", "₹20,000")
        d.metric("Maximum open stocks", 3)
        selection = select_nifty_stocks(client, key="portfolio_universe")
        periods = strategy_profile(mode).allowed_periods
        period = st.selectbox(
            "Kite OHLCV history", periods, index=1 if mode == "swing" else 2
        )
        options = selection["symbols"]
        if source == "Scanner matches":
            if st.button("Scan stocks", disabled=not authorized or not options):
                st.session_state.pop("tf_r726_scan_result", None)
                try:
                    st.session_state["tf_r726_scan_result"] = scan_nifty_stocks(
                        client,
                        selection,
                        mode=mode,
                        period=period,
                        strategy_id=strategy_id,
                    )
                except ApiError as exc:
                    render_api_error(exc, title="Scanner unavailable")
            snapshot = st.session_state.get("tf_r726_scan_result", {})
            signal = st.selectbox(
                "Signal filter", ["BUY", "SELL", "WAIT", "EXIT", "All signals"]
            )
            rows = (
                matching_rows(snapshot, mode, signal, 0)
                if snapshot.get("strategy_id") == strategy_id
                else []
            )
            scope = snapshot.get("universe")
            if isinstance(scope, dict) and (
                scope.get("index") != selection["index"]
                or scope.get("sector") != selection["sector"]
            ):
                rows = []
                st.info("Run the scanner for the selected Nifty list and sector.")
            rows = [row for row in rows if row["symbol"] in options]
            options = [row["symbol"] for row in rows]
            if rows:
                with results_panel:
                    render_candidate_analysis(
                        rows,
                        daily=mode == "swing",
                        key="portfolio_candidates",
                        controls=controls,
                    )
            else:
                st.info(
                    "No stocks match. Run the selected scanner "
                    "or change its signal filter."
                )
            st.warning(
                "Today's scanner matches can bias historical results. "
                "This does not reconstruct historical index membership "
                "or past scanner selections."
            )
        else:
            st.caption(
                "Historical entry candidates are ranked at each completed candle. "
                "Today's Nifty membership is a fixed research universe, "
                "not historical membership."
            )
        with st.form("shared_portfolio_backtest"):
            selected = st.multiselect(
                "Stocks to backtest",
                options,
                default=options if len(options) <= 100 else [],
                max_selections=100,
            )
            cost = st.number_input(
                "Transaction cost (basis points per side)",
                min_value=0.0,
                max_value=1000.0,
                value=12.0,
            )
            slip = st.number_input(
                "Slippage (basis points per side)",
                min_value=0.0,
                max_value=1000.0,
                value=5.0,
            )
            st.caption(
                "Select up to 100 candidate stocks; only the top eligible three "
                "may be held concurrently. New-entry budgets are proportional "
                "to their signal scores. Whole-share rounding leaves unused cash idle."
            )
            action = (
                "Backtest selected stocks"
                if source == "Scanner matches"
                else "Run Kite backtest"
            )
            run = st.form_submit_button(
                action, type="primary", disabled=not authorized or not options
            )
        if not authorized:
            st.info("The Admin API Key is required to run historical backtests.")
        if run:
            st.session_state.pop(RESULT_KEY, None)
            if not selected:
                st.error("Select stocks from the current list.")
            else:
                try:
                    with st.spinner("Running the shared-cash portfolio backtest…"):
                        result = client.post_json(
                            "/technical/portfolio-backtest",
                            {
                                "symbols": selected,
                                "mode": mode,
                                "strategy_id": strategy_id,
                                "period": period,
                                "cost_bps": float(cost),
                                "slippage_bps": float(slip),
                                "run_id": "portfolio-ui-" + uuid4().hex,
                            },
                            timeout=240,
                        )
                    validate_result(result)
                    st.session_state[RESULT_KEY] = result
                except ApiError as exc:
                    render_api_error(exc, title="Historical portfolio backtest failed")
        result = st.session_state.get(RESULT_KEY)
        if (
            isinstance(result, dict)
            and result.get("parameters", {}).get("max_positions") == 3
        ):
            with results_panel:
                render_result(result, controls=controls)

    if source == "Nifty list / sector" and not isinstance(result, dict):
        with results_panel:
            st.subheader("Candidate universe")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"symbol": symbol, "signal": "NOT_SCANNED", "score": None}
                        for symbol in options
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
