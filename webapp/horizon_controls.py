"""Only current scanner choices; reset obsolete browser selections."""

import streamlit as st

from scanner.strategy_horizons import HORIZONS, scanner_horizon_choices


def select_horizon_strategy(*, key):
    available = [
        (horizon, label, scanner_horizon_choices(horizon))
        for horizon, label in HORIZONS.items()
    ]
    available = [item for item in available if item[2]]
    if not available:
        st.info("No scanner strategy is currently available.")
        st.stop()
    # One selector preserves the established weekly default and offers daily research.
    available.sort(key=lambda item: item[0] != "long_term")
    choices = {name: row for _, _, group in available for name, row in group.items()}
    widget_key = key + "_research_strategy"
    if st.session_state.get(widget_key) not in choices:
        st.session_state.pop(widget_key, None)
    choice = st.selectbox("Research strategy", list(choices), key=widget_key)
    st.session_state[key + "_horizon"] = HORIZONS[choices[choice]["horizon"]]
    return dict(choices[choice])
