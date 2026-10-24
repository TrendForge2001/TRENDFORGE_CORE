"""Read-only P&L dashboard for independent historical backtest allocations."""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from webapp.paper_excel import safe_csv_bytes
from webapp.trade_timestamps import (
    export_trade_frame,
    format_trade_frame,
    market_timestamp,
)


def _number(value) -> float:
    if isinstance(value, bool):
        raise ValueError("Invalid financial figure")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Missing or invalid financial figure") from None
    if not math.isfinite(number):
        raise ValueError("Invalid financial figure")
    return number


def build_backtest_pnl(results: list[dict]) -> dict:
    """Use saved engine metrics; never treat failed/absent runs as zero returns."""
    if not results:
        raise ValueError("No completed backtests")
    allocations = []
    trades = []
    series = []
    curve_complete = True
    warnings = []
    fees = []
    slippage = []
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            raise ValueError("Invalid backtest result")
        if result.get("status") != "completed":
            raise ValueError("Only completed runs belong in P&L")
        metrics = result["metrics"]
        if not isinstance(metrics, dict):
            raise ValueError("Invalid backtest metrics")
        fees.append(
            _number(metrics["transaction_costs"])
            if metrics.get("transaction_costs") is not None
            else None
        )
        slippage.append(
            _number(metrics["slippage_impact_estimate"])
            if metrics.get("slippage_impact_estimate") is not None
            else None
        )
        initial = _number(metrics.get("initial_capital"))
        final = _number(metrics.get("final_capital"))
        net = _number(metrics.get("net_profit"))
        if initial <= 0 or abs(final - initial - net) > 0.02:
            raise ValueError("Backtest capital does not reconcile")
        ledger = result.get("trades")
        if (
            not isinstance(ledger, list)
            or not all(isinstance(row, dict) for row in ledger)
            or type(metrics.get("total_trades")) is not int
            or metrics.get("total_trades") != len(ledger)
        ):
            raise ValueError("Backtest trade count does not reconcile")
        ledger_net = math.fsum(_number(row.get("net_pnl")) for row in ledger)
        if abs(ledger_net - net) > 0.02 + len(ledger) * 0.01:
            raise ValueError("Backtest trade P&L does not reconcile")
        symbol = result.get("symbol") or "Unknown"
        if not isinstance(result.get("strategy", {}), dict) or not isinstance(
            result.get("parameters", {}), dict
        ):
            raise ValueError("Invalid backtest evidence")
        strategy = (result.get("strategy") or {}).get("name") or "Technical"
        daily = (
            result.get("interval") == "1d"
            or (result.get("parameters") or {}).get("mode") == "swing"
        )
        allocations.append(
            {
                "Stock": symbol,
                "Strategy": strategy,
                "Initial capital (₹)": initial,
                "Final capital (₹)": final,
                "Net P&L (₹)": net,
                "Return (%)": net / initial * 100,
                "Trades": len(ledger),
            }
        )
        for row in ledger:
            exit_stamp = market_timestamp(row.get("exit_at"))
            entry_stamp = market_timestamp(row.get("entry_at"))
            if entry_stamp and exit_stamp and exit_stamp < entry_stamp:
                warnings.append(
                    f"{symbol}: exit precedes entry; review source evidence."
                )
            if entry_stamp is None:
                warnings.append(f"{symbol}: trade has no valid entry timestamp.")
            if exit_stamp is None:
                warnings.append(
                    f"{symbol}: trade has no valid exit date; excluded from daily P&L."
                )
            trades.append(
                {
                    **row,
                    "symbol": symbol,
                    "strategy": strategy,
                    "exit_day_ist": exit_stamp.date().isoformat()
                    if exit_stamp
                    else None,
                    "daily_bar": daily,
                }
            )
        points = []
        try:
            for point in result.get("equity_curve") or []:
                if not isinstance(point, dict):
                    raise ValueError("Invalid equity observations")
                stamp = market_timestamp(point.get("date"))
                if stamp is None:
                    raise ValueError("Invalid equity date")
                points.append((stamp, _number(point.get("equity"))))
            if not points:
                raise ValueError("No equity observations")
            values = pd.Series(
                [value for _, value in points],
                index=pd.DatetimeIndex([stamp for stamp, _ in points]),
            )
            values = values[~values.index.duplicated(keep="last")].sort_index()
            if abs(float(values.iloc[-1]) - final) > 0.02:
                raise ValueError("Equity does not reconcile")
            series.append((values, initial, index))
        except (ValueError, TypeError, KeyError):
            curve_complete = False
    capital = math.fsum(row["Initial capital (₹)"] for row in allocations)
    final = math.fsum(row["Final capital (₹)"] for row in allocations)
    net = math.fsum(row["Net P&L (₹)"] for row in allocations)
    pnls = [_number(row["net_pnl"]) for row in trades]
    profits = math.fsum(value for value in pnls if value > 0)
    losses = math.fsum(value for value in pnls if value < 0)
    daily_rows = pd.DataFrame(
        [
            {"Exit date (IST)": row["exit_day_ist"], "Net P&L (₹)": row["net_pnl"]}
            for row in trades
            if row["exit_day_ist"] is not None
        ]
    )
    if not daily_rows.empty:
        daily_rows = daily_rows.groupby("Exit date (IST)", as_index=False)[
            "Net P&L (₹)"
        ].sum()
        daily_rows["Cumulative realized P&L (₹)"] = daily_rows["Net P&L (₹)"].cumsum()
    curve = pd.DataFrame()
    max_drawdown = None
    if curve_complete and series:
        timeline = series[0][0].index
        for values, _, _ in series[1:]:
            timeline = timeline.union(values.index)
        timeline = timeline.sort_values()
        total = sum(
            values.reindex(timeline).ffill().fillna(initial)
            for values, initial, _ in series
        )
        peaks = total.cummax().clip(lower=capital)
        drawdown = (total / peaks - 1) * 100
        max_drawdown = abs(float(drawdown.min()))
        curve = pd.DataFrame(
            {
                "Time (IST)": [
                    stamp.strftime("%Y-%m-%d %H:%M:%S") for stamp in timeline
                ],
                "Equity (₹)": total.to_numpy(),
                "Equity P&L (₹)": total.to_numpy() - capital,
                "Drawdown (%)": drawdown.to_numpy(),
            }
        )
    return {
        "fees": math.fsum(fees) if all(value is not None for value in fees) else None,
        "slippage": math.fsum(slippage)
        if all(value is not None for value in slippage)
        else None,
        "capital": capital,
        "final": final,
        "net": net,
        "return_pct": net / capital * 100,
        "trades": trades,
        "allocations": allocations,
        "daily": daily_rows,
        "curve": curve,
        "max_drawdown": max_drawdown,
        "gross_profit": profits,
        "gross_loss": losses,
        "win_rate": sum(value > 0 for value in pnls) / len(pnls) * 100 if pnls else 0,
        "profit_factor": profits / abs(losses) if losses else None,
        "warnings": list(dict.fromkeys(warnings)),
    }


def render_backtest_pnl(results: list[dict], *, key: str, failed: int = 0) -> None:
    st.subheader("Backtesting P&L dashboard")
    if not results:
        st.info("No completed stock simulations are available for P&L.")
        return
    if len(results) > 1:
        choice = st.selectbox(
            "P&L view",
            [-1, *range(len(results))],
            key=key + "_scope",
            format_func=lambda index: (
                "All completed stocks"
                if index == -1
                else str(results[index].get("symbol") or "Unknown")
            ),
        )
        if choice != -1:
            results = [results[choice]]
    try:
        report = build_backtest_pnl(results)
    except (ValueError, TypeError, KeyError, OverflowError):
        st.info(
            "Detailed P&L is unavailable: saved capital and trade-ledger "
            "evidence is incomplete or inconsistent."
        )
        return
    if failed:
        st.warning(
            f"{failed} failed stock simulations are excluded from P&L "
            "and allocated capital."
        )
    st.caption(
        "Independent capital allocation per stock; totals cover completed "
        "simulations only. Returns include configured fees and fill slippage. "
        "Slippage is already in fill prices and is not deducted again."
    )
    a, b, c, d = st.columns(4)
    a.metric("Net backtest P&L", f"₹{report['net']:,.2f}")
    b.metric("Allocated capital", f"₹{report['capital']:,.2f}")
    c.metric("Ending capital", f"₹{report['final']:,.2f}")
    d.metric("Allocation return", f"{report['return_pct']:.2f}%")
    a, b, c, d = st.columns(4)
    a.metric("Winning trade P&L", f"₹{report['gross_profit']:,.2f}")
    b.metric("Losing trade P&L", f"₹{report['gross_loss']:,.2f}")
    c.metric("Closed trades", len(report["trades"]))
    d.metric(
        "Combined drawdown",
        "Unavailable"
        if report["max_drawdown"] is None
        else f"{report['max_drawdown']:.2f}%",
    )
    with st.expander("Costs and trade statistics"):
        a, b, c, d = st.columns(4)
        a.metric("Trade win rate", f"{report['win_rate']:.2f}%")
        b.metric(
            "Net profit factor",
            "—"
            if report["profit_factor"] is None
            else f"{report['profit_factor']:.2f}",
        )
        c.metric(
            "Transaction fees",
            "Unavailable" if report["fees"] is None else f"₹{report['fees']:,.2f}",
        )
        d.metric(
            "Slippage estimate (included)",
            "Unavailable"
            if report["slippage"] is None
            else f"₹{report['slippage']:,.2f}",
        )
    for warning in report["warnings"]:
        st.warning(warning)
    if not report["curve"].empty:
        equity, drawdown = st.tabs(["Equity P&L", "Drawdown"])
        with equity:
            st.line_chart(report["curve"].set_index("Time (IST)")[["Equity P&L (₹)"]])
        with drawdown:
            st.area_chart(report["curve"].set_index("Time (IST)")[["Drawdown (%)"]])
    else:
        st.info(
            "The saved equity observations are incomplete; "
            "no combined curve or drawdown is estimated."
        )
    st.caption(
        "Historical entry/exit timestamps identify candle bars, not exact tick fills. "
        "Daily bars show their date; intraday and paper/broker timestamps use "
        "DD Mon YYYY, HH:mm:ss IST. Naive market times follow the existing IST "
        "contract. Exports retain raw timestamps plus IST columns."
    )
    st.dataframe(
        pd.DataFrame(report["allocations"]), hide_index=True, use_container_width=True
    )
    st.download_button(
        "Export P&L allocation summary (CSV)",
        safe_csv_bytes(pd.DataFrame(report["allocations"])),
        "trendforge_backtest_pnl_summary.csv",
        "text/csv",
        key=key + "_summary",
    )
    daily = report["daily"]
    if not daily.empty:
        st.subheader("Realized P&L by exit date")
        st.bar_chart(daily.set_index("Exit date (IST)")[["Net P&L (₹)"]])
        st.dataframe(daily, hide_index=True, use_container_width=True)
        st.download_button(
            "Export daily backtest P&L (CSV)",
            safe_csv_bytes(daily),
            "trendforge_backtest_daily_pnl.csv",
            "text/csv",
            key=key + "_daily",
        )
    trades = report["trades"]
    if trades:
        st.subheader("Entry / exit trade details")
        ledger = pd.DataFrame(trades)
        display = pd.concat(
            [
                format_trade_frame(group, daily=bool(daily))
                for daily, group in ledger.groupby("daily_bar", sort=False)
            ]
        ).sort_index()
        st.dataframe(display, hide_index=True, use_container_width=True)
        exported = pd.concat(
            [
                export_trade_frame(group, daily=bool(daily))
                for daily, group in ledger.groupby("daily_bar", sort=False)
            ]
        ).sort_index()
        st.download_button(
            "Export backtest P&L trades (CSV)",
            safe_csv_bytes(exported),
            "trendforge_backtest_pnl_trades.csv",
            "text/csv",
            key=key + "_trades",
        )
