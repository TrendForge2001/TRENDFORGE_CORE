"""Actual indicator evidence and indicative shared-account allocation."""

import pandas as pd
import streamlit as st

from scanner.portfolio_policy import (
    DEPLOYMENT_LIMIT,
    MAX_POSITIONS,
    allocate_candidates,
    evidence_rows,
)
from webapp.paper_excel import safe_csv_bytes
from webapp.trade_timestamps import export_trade_frame, format_trade_frame


def render_candidate_analysis(rows: list[dict], *, daily: bool, key: str) -> None:
    st.subheader("Stock risk/reward and technical indicator values")
    frame = pd.DataFrame(evidence_rows(rows))
    if frame.empty:
        st.info("No scanner evidence is available.")
        return
    st.caption(
        "Risk:reward = 1:(target − entry)/(entry − stop). Price-based ratios "
        "exclude fees and are not win probabilities. Indicator values belong "
        "to the displayed completed candle; HOLD is not a BUY instruction."
    )
    st.dataframe(
        format_trade_frame(frame, daily=daily),
        hide_index=True,
        use_container_width=True,
    )
    st.download_button(
        "Export stock indicator evidence (CSV)",
        safe_csv_bytes(export_trade_frame(frame, daily=daily)),
        "trendforge_stock_indicators.csv",
        "text/csv",
        key=key + "_evidence",
    )
    selected = allocate_candidates(rows, budget=DEPLOYMENT_LIMIT, slots=MAX_POSITIONS)
    if not selected:
        st.info("No valid BUY setups: the ₹80,000 trading budget remains unallocated.")
        return
    preview = []
    for row in selected:
        quantity = int(row["allocation_budget"] / (row["entry"] * 1.0005 * 1.0012))
        preview.append(
            {
                "Stock": row["symbol"],
                "Score": row["score"],
                "Weight (%)": row["weight_pct"],
                "Budget (₹)": row["allocation_budget"],
                "Indicative quantity": quantity,
                "Risk:reward": row["risk_reward"],
                "Risk/share (₹)": row["risk_per_share"],
                "Reward/share (₹)": row["reward_per_share"],
                "Gross risk (₹)": quantity * row["risk_per_share"],
                "Gross reward (₹)": quantity * row["reward_per_share"],
            }
        )
    st.subheader("Top three BUY candidates — backtest allocation preview")
    st.dataframe(pd.DataFrame(preview), hide_index=True, use_container_width=True)
    st.caption(
        "₹80,000 × stock score / total selected BUY scores; equal scores give "
        "equal budgets. Quantities are indicative at the signal price with 12 bps "
        "cost and 5 bps slippage. Whole shares can leave extra cash idle. Historical "
        "backtests recalculate rankings at each candle, not from today's scores. "
        "This preview does not change live-paper risk settings or place orders."
    )
