"""Only current scanner choices; reset obsolete browser selections."""

import streamlit as st

from scanner.strategy_horizons import HORIZONS, scanner_horizon_choices


def select_horizon_strategy(*, key, default_horizon="long_term"):
    available = [
        (horizon, label, scanner_horizon_choices(horizon))
        for horizon, label in HORIZONS.items()
    ]
    available = [item for item in available if item[2]]
    if not available:
        st.info("No scanner strategy is currently available.")
        st.stop()
    labels = {label: (horizon, group) for horizon, label, group in available}
    default = next(
        (label for horizon, label, _ in available if horizon == default_horizon),
        available[0][1],
    )
    label = st.segmented_control(
        "Horizon", list(labels), default=default, key=key + "_horizon_choice"
    )
    horizon, choices = labels[label or default]
    # A different option set needs a different widget identity. Reusing a
    # keyed selectbox after deleting its value can leave the old browser label
    # visible even when the backend has selected the new horizon's default.
    widget_key = key + "_" + horizon + "_research_strategy"
    if st.session_state.get(widget_key) not in choices:
        st.session_state.pop(widget_key, None)
    choice = st.selectbox("Research strategy", list(choices), key=widget_key)
    st.session_state[key + "_horizon"] = HORIZONS[choices[choice]["horizon"]]
    return dict(choices[choice])
