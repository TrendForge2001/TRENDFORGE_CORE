"""Account-level comparison without adding strategy or report dropdowns."""

import pandas as pd
import streamlit as st


def render_weekly_comparisons(report):
    st.subheader("Shared-account comparison")
    st.caption(
        "One ₹1 lakh account per comparison; 12 bps fees and 5 bps slippage per leg. "
        "Baseline retains legacy sizing. The next three stages "
        "add the proposed rules in order."
    )
    columns = [
        "variant",
        "net_profit",
        "change_net_profit",
        "max_drawdown_pct",
        "change_max_drawdown_pct",
        "profit_factor",
        "skipped_trades",
        "largest_winner",
        "top_5_share_of_gross_profits_pct",
        "net_profit_without_top_1",
        "net_profit_without_top_5",
    ]
    st.dataframe(
        pd.DataFrame(report["comparisons"])[columns], hide_index=True, width="stretch"
    )
    rows = [
        {"variant": run["variant"], **p}
        for run in report["comparison_results"]
        for p in run["equity_curve"]
    ]
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame.date, utc=True).dt.tz_convert("Asia/Kolkata")
    equity = frame.pivot(index="date", columns="variant", values="equity")
    benchmark = frame.drop_duplicates("date").set_index("date")["benchmark_equity"]
    if benchmark.notna().any():
        equity["NIFTY 100 price index"] = benchmark
    st.line_chart(equity)
    st.caption(
        "Daily marks precede terminal liquidation costs. Benchmark is a price index, "
        "without dividends or implementation costs; it is not an index trend filter."
    )
    if report["benchmark"]["status"] != "complete":
        st.warning(
            "Benchmark coverage is incomplete: "
            + str(report["benchmark"]["error_code"])
        )
    with st.expander("Daily drawdown, exposure and planned open risk"):
        st.dataframe(frame, hide_index=True, width="stretch")
    with st.expander("Terminal reconciliation and skipped trades"):
        st.dataframe(
            pd.DataFrame(report["comparisons"])[
                [
                    "variant",
                    "final_equity_before_terminal",
                    "final_capital",
                    "terminal_liquidation_drag",
                    "terminal_net_pnl",
                    "skip_reasons",
                ]
            ],
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "The Excel download includes every variant's trades, daily equity, "
            "entry risk audit, skipped entries, terminal liquidations "
            "and stock coverage. "
            "Missing stock bars carry stale valuation flags and never create fills."
        )
