"""Closed paper-trade P&L statement."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "P&L Statement",
    "Calendar-period realized P&L from closed TrendForge paper trades, with trade-level evidence and daily aggregation.",
    kicker="Performance",
)

info_note(
    "This statement covers closed paper trades only. It does not combine broker holdings P&L with simulated trading P&L."
)

period = st.segmented_control(
    "Period",
    options=["daily", "weekly", "monthly", "yearly", "all"],
    default="monthly",
)

client = api_client(timeout=60)
try:
    report = client.get_json(
        "/pnl",
        params={"period": period or "monthly"},
    )
except ApiError as exc:
    render_api_error(
        exc,
        title="P&L statement unavailable",
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
        "Gross profit",
        f"₹{float(summary.get('gross_profit') or 0):,.2f}",
    )
with m3:
    st.metric(
        "Gross loss",
        f"₹{float(summary.get('gross_loss') or 0):,.2f}",
    )
with m4:
    st.metric(
        "Trades",
        int(summary.get("trade_count") or 0),
    )
with m5:
    st.metric(
        "Capital employed",
        f"₹{float(summary.get('capital_employed_sum') or 0):,.2f}",
    )
with m6:
    st.metric(
        "P&L margin",
        f"{float(summary.get('pnl_margin_pct') or 0):.2f}%",
    )

st.caption(
    f"Window: {report.get('period_start') or 'all history'} → "
    f"{report.get('period_end') or 'now'} · "
    f"Date basis: {report.get('date_basis') or 'unknown'}"
)

daily = report.get("daily")
daily = daily if isinstance(daily, list) else []
if daily:
    st.subheader("Daily realized P&L")
    daily_frame = pd.DataFrame(daily)
    if "date" in daily_frame and "net_pnl" in daily_frame:
        st.bar_chart(
            daily_frame.set_index("date")[["net_pnl"]]
        )
    st.dataframe(
        daily_frame,
        use_container_width=True,
        hide_index=True,
    )

trades = report.get("trades")
trades = trades if isinstance(trades, list) else []
st.subheader("Closed trades")
if trades:
    trade_frame = pd.DataFrame(trades)
    st.dataframe(
        trade_frame,
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Download P&L CSV",
        data=trade_frame.to_csv(index=False).encode("utf-8"),
        file_name=f"trendforge_pnl_{period or 'monthly'}.csv",
        mime="text/csv",
    )

    legacy = trade_frame[
        trade_frame.get(
            "date_basis",
            pd.Series(dtype=str),
        )
        == "legacy_entry_fallback"
    ]
    if not legacy.empty:
        st.warning(
            f"{len(legacy)} legacy closed trade(s) do not have a close timestamp; "
            "their entry timestamp is used for period attribution."
        )
else:
    st.info("No closed paper trades in this period.")
