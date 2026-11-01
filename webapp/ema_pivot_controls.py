"""Compact research options, kept on the controls side of existing tabs."""

import streamlit as st

from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS


def research_options(strategy_id, *, key, backtest=False) -> dict:
    if strategy_id not in EMA_PIVOT_SETUPS:
        return {}
    st.info(
        "Research scanner and backtest only. BUY/SELL means an armed setup; "
        "the next candle must trigger entry. These eight setups do not start "
        "automatic paper trades."
    )
    volume = st.checkbox(
        "Require volume > 1.5 × preceding 20 candles", value=False, key=key + "_volume"
    )
    st.caption(
        "Signal candle excluded. This is not a same-time-of-day volume comparison."
    )
    tick = st.number_input(
        "Tick size assumption (₹)",
        min_value=0.01,
        max_value=100.0,
        value=0.05,
        step=0.01,
        key=key + "_tick",
    )
    result = {"liquidity_confirmation": volume, "tick_size": float(tick)}
    if backtest and EMA_PIVOT_SETUPS[strategy_id].direction == -1:
        result["short_borrow_available"] = st.checkbox(
            "Assume borrow is available for this historical short simulation",
            value=False,
            key=key + "_borrow",
        )
        st.caption(
            "This is a backtest assumption. The application does not verify "
            "borrow or submit broker orders."
        )
    return result
