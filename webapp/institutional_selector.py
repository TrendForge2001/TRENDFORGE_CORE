"""One owner-controlled conditional filter shared across scanner pages."""

import time

import streamlit as st

KEY = "tf_institutional_signal_filter"


def selected_signal():
    return st.session_state.get(KEY, "All stocks")


def render_selector():
    st.selectbox(
        "Big Shark stock selector",
        ("All stocks", "BUY", "SELL", "HOLD", "NO_DATA"),
        key=KEY,
        help=(
            "Compare actual bought and sold quantities or INR values. "
            "Awaiting trade data until actual flows are supplied."
        ),
    )


def filter_symbols(client, symbols):
    signal = selected_signal()
    if signal == "All stocks":
        return symbols
    cached = st.session_state.get("tf_big_shark_filter_snapshot")
    cache_key = getattr(client, "base_url", "")
    if cached is None or cached[0] != cache_key or time.monotonic() - cached[1] > 60:
        payload = client.get_json("/institutional/big-shark")
        cached = (cache_key, time.monotonic(), payload)
        st.session_state["tf_big_shark_filter_snapshot"] = cached
    allowed = {
        row["symbol"]
        for row in cached[2].get("signals", [])
        if row.get("symbol") and row.get("signal") == signal
    }
    return [symbol for symbol in symbols if symbol in allowed]
