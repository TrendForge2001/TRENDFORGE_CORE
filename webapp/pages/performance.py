"""Paper-trading performance analytics dashboard."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Performance Dashboard",
    "Evaluate closed TrendForge paper trades using profitability, expectancy, drawdown and cumulative realized P&L.",
    kicker="Analytics",
)

info_note(
    "Performance metrics are calculated from closed paper trades. "
    "They are execution analytics, not a forecast of future returns."
)

period = st.segmented_control(
    "Period",
    options=["daily", "weekly", "monthly", "yearly", "all"],
    default="monthly",
    key="performance_period",
)

client = api_client(timeout=60)
try:
    report = client.get_json(
        "/performance",
        params={"period": period or "monthly"},
    )
except ApiError as exc:
    render_api_error(
        exc,
        title="Performance report unavailable",
    )
    st.stop()

summary = report.get("summary")
summary = summary if isinstance(summary, dict) else {}

m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.metric(
        "Net P&L",
        f"₹{float(summary.get('net_pnl') or 0):,.2f}",
    )
with m2:
    st.metric(
        "Win rate",
        f"{float(summary.get('win_rate_pct') or 0):.2f}%",
    )
with m3:
    factor = summary.get("profit_factor")
    st.metric(
        "Profit factor",
        "—" if factor is None else f"{float(factor):.2f}",
    )
with m4:
    st.metric(
        "Expectancy",
        f"₹{float(summary.get('expectancy') or 0):,.2f}",
    )
with m5:
    st.metric(
        "Max drawdown",
        f"₹{float(summary.get('maximum_drawdown') or 0):,.2f}",
    )
with m6:
    st.metric(
        "Trades",
        int(summary.get("trade_count") or 0),
    )

s1, s2, s3, s4 = st.columns(4)
with s1:
    st.metric(
        "Avg winner",
        f"₹{float(summary.get('average_winner') or 0):,.2f}",
    )
with s2:
    st.metric(
        "Avg loser",
        f"₹{float(summary.get('average_loser') or 0):,.2f}",
    )
with s3:
    st.metric(
        "Winning trades",
        int(summary.get("winning_trades") or 0),
    )
with s4:
    st.metric(
        "Losing trades",
        int(summary.get("losing_trades") or 0),
    )

curve = report.get("equity_curve")
curve = curve if isinstance(curve, list) else []
if curve:
    st.subheader("Cumulative realized P&L")
    curve_frame = pd.DataFrame(curve)
    if (
        "realized_at" in curve_frame
        and "cumulative_pnl" in curve_frame
    ):
        chart_frame = curve_frame.copy()
        chart_frame["realized_at"] = pd.to_datetime(
            chart_frame["realized_at"],
            errors="coerce",
        )
        chart_frame = chart_frame.dropna(
            subset=["realized_at"]
        )
        if not chart_frame.empty:
            st.line_chart(
                chart_frame.set_index("realized_at")[
                    ["cumulative_pnl"]
                ]
            )
    st.dataframe(
        curve_frame,
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No closed trades are available for an equity curve.")

left, right = st.columns(2)
with left:
    st.subheader("Best trade")
    best = summary.get("best_trade")
    if isinstance(best, dict):
        st.json(best)
    else:
        st.info("No trade available.")
with right:
    st.subheader("Worst trade")
    worst = summary.get("worst_trade")
    if isinstance(worst, dict):
        st.json(worst)
    else:
        st.info("No trade available.")

daily = report.get("daily")
daily = daily if isinstance(daily, list) else []
if daily:
    with st.expander("Daily performance evidence"):
        st.dataframe(
            pd.DataFrame(daily),
            use_container_width=True,
            hide_index=True,
        )
