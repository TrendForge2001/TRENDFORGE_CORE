"""Visible review-only source strategies, with no guessed execution rules."""

from contextlib import nullcontext

import pandas as pd
import streamlit as st

from scanner.strategy_registry import ACTIVE_STRATEGY_IDS, get_strategy
from webapp.nifty_selection import select_nifty_stocks


def render_review_scanner(client, strategy_id: str, *, key: str, results=None) -> None:
    strategy = get_strategy(strategy_id)
    st.subheader(strategy["name"])
    st.caption(
        "Source-derived scanner / strategy · " + ", ".join(strategy["intervals"])
    )
    st.write("Indicators: " + ", ".join(strategy["indicators"]))
    st.warning(
        "Review required: source confirmation, target and stop rules are incomplete. "
        "Scanning, backtesting and new paper entries remain blocked for this strategy."
    )
    with st.expander("Source rules and open points", expanded=True):
        st.write(strategy["entry_rules"] + strategy["exit_rules"] + strategy["notes"])
    selection = select_nifty_stocks(client, key=key)
    with results if results is not None else nullcontext():
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "strategy": strategy["name"],
                        "signal": "REVIEW_REQUIRED",
                        "score": None,
                    }
                    for symbol in selection["symbols"]
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    st.button("Run technical scan", disabled=True, key=key + "_scan")
    st.button("Run Kite backtest", disabled=True, key=key + "_backtest")


def clear_retired_scan_cache() -> None:
    cached = st.session_state.get("tf_r726_scan_result")
    if (
        isinstance(cached, dict)
        and cached.get("strategy_id") not in ACTIVE_STRATEGY_IDS
    ):
        st.session_state.pop("tf_r726_scan_result", None)
        st.info(
            "The previous scanner selection was retired. "
            "Run an active TrendForge strategy."
        )
