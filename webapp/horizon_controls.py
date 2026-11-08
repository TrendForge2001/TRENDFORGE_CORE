"""One separate strategy dropdown per horizon, shown in the selected tab."""

import streamlit as st

from scanner.strategy_horizons import HORIZONS, horizon_strategies


def select_horizon_strategy(*, key):
    tabs = st.tabs(
        list(HORIZONS.values()),
        key=key + "_horizon",
        default="Short Swing",
        on_change="rerun",
    )
    selected = None
    for (horizon, label), tab in zip(HORIZONS.items(), tabs, strict=True):
        if tab.open:
            with tab:
                choices = horizon_strategies(horizon)
                choice = st.selectbox(
                    label + " strategy", list(choices), key=key + "_" + horizon
                )
                selected = choices[choice]
    if selected is None:
        # The default is explicit, including test clients without tab interaction.
        horizon = "short_swing"
        choices = horizon_strategies(horizon)
        with tabs[1]:
            choice = st.selectbox(
                "Short Swing strategy", list(choices), key=key + "_short_swing"
            )
        selected = choices[choice]
    return selected
