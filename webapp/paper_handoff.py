"""Explicit operator start for scanner stocks; all candidates are re-evaluated."""

import streamlit as st

from scanner.strategy_registry import ACTIVE_STRATEGY_IDS, get_strategy
from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured
from webapp.ui import render_api_error


def render_scanner_paper_handoff(client, snapshot: dict) -> None:
    notice = st.session_state.pop("tf_scanner_paper_notice", None)
    if notice:
        st.success(notice)
    strategy_id = snapshot.get("strategy_id")
    if strategy_id not in ACTIVE_STRATEGY_IDS:
        return
    if not get_strategy(strategy_id)["paper_eligible"]:
        return
    stocks = list(
        dict.fromkeys(
            row["symbol"]
            for row in snapshot.get("results", [])
            if row.get("signal") == "BUY" and row.get("symbol")
        )
    )
    st.subheader("Paper trade scanner candidates")
    st.caption(
        "Start is an operator command. The server re-scans these stocks, "
        "validates the strategy against NIFTY 500, and requires current candles, "
        "fresh quotes and paper risk approval. Stocks outside NIFTY 500 are "
        "rejected. No broker orders are submitted."
    )
    selected = st.multiselect(
        "Potential stocks for paper trading (up to 100)",
        stocks,
        default=stocks if len(stocks) <= 100 else [],
        key="scanner_paper_targets",
    )
    state = None
    try:
        state = client.get_json("/paper/automation")
        if type(state.get("enabled")) is not bool:
            raise ApiError("Invalid paper automation status")
    except ApiError as exc:
        state = None
        render_api_error(exc, title="Paper trading controls unavailable")
    if state is not None:
        st.caption(
            "Paper automation: "
            + ("ON" if state["enabled"] else "OFF")
            + " · "
            + str(state.get("phase"))
        )
        if state.get("blockers"):
            st.warning("Paper start blockers: " + ", ".join(state["blockers"]))
        ready = (
            admin_key_configured()
            and not state["enabled"]
            and not state.get("blockers")
            and state.get("worker_running") is True
            and 1 <= len(selected) <= 100
        )
        if st.button(
            "Start paper trading selected stocks", type="primary", disabled=not ready
        ):
            try:
                client.put_json(
                    "/paper/automation",
                    {
                        "enabled": True,
                        "universe": "NIFTY 500",
                        "symbols": selected,
                        "strategy_ids": [strategy_id],
                    },
                )
                st.session_state["tf_scanner_paper_notice"] = (
                    "Paper automation armed for the selected stocks. New entries "
                    "wait for validation and fresh market signals."
                )
                st.rerun()
            except ApiError as exc:
                render_api_error(
                    exc, title="Selected-stock paper trading could not start"
                )
    if st.button(
        "Stop automated paper trading",
        key="scanner_paper_stop",
        disabled=not admin_key_configured(),
    ):
        try:
            client.put_json("/paper/automation", {"enabled": False})
            st.session_state["tf_scanner_paper_notice"] = (
                "New automated paper entries stopped. "
                "Existing positions remain monitored."
            )
            st.rerun()
        except ApiError as exc:
            render_api_error(exc, title="Paper stop failed; use the paper kill switch")
