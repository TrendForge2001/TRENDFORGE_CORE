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
    # Only the approved weekly strategy is selectable. Remove obsolete widget
    # values after upgrades without touching saved batch reports or positions.
    horizon, label, choices = available[0]
    st.session_state[key + "_horizon"] = label
    widget_key = key + "_" + horizon
    if st.session_state.get(widget_key) not in choices:
        st.session_state.pop(widget_key, None)
    choice = st.selectbox(label + " strategy", list(choices), key=widget_key)
    return dict(choices[choice])
