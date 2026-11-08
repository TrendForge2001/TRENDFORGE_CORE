"""Clean research controls; run state and detailed reports live on Reports."""

import streamlit as st

from config.nifty_universes import NIFTY_UNIVERSES
from core.deployment_role import cloud_read_only
from webapp.api_client import ApiError
from webapp.backtest_controls import stock_list
from webapp.horizon_controls import select_horizon_strategy
from webapp.ui import render_api_error


def submit_research(client, settings, selection, kind):
    response = client.post_json(
        "/reports/" + kind,
        {
            "horizon": settings["horizon"],
            "strategy_id": settings["strategy_id"],
            "stock_list": selection["index"],
            "symbols": selection["symbols"],
            "short_borrow_available": settings["short_borrow_available"],
        },
        timeout=20,
    )
    if not isinstance(response.get("batch_id"), str) or response.get("status") not in {
        "queued",
        "running",
        "completed",
        "failed",
        "interrupted",
    }:
        raise ApiError("The backend did not acknowledge a research batch")
    st.session_state["tf_report_selected_batch"] = response["batch_id"]
    return response


def render_research_workspace(client, *, authorized, key, backtest=True):
    settings = select_horizon_strategy(key=key)
    if cloud_read_only():
        st.caption(
            "Research runs continue on the cloud server while this page is closed. "
            "Reports shows the actual storage source and durability."
        )
    index = st.selectbox("Stock list", list(NIFTY_UNIVERSES), key=key + "_stocks")
    scope = (settings["horizon"], settings["strategy_id"], index)
    if st.session_state.get(key + "_scope") != scope:
        st.session_state.pop(key + "_batch", None)
        st.session_state[key + "_scope"] = scope
    selection = {"symbols": [], "index": index}
    try:
        selection = stock_list(client, index)
    except ApiError as exc:
        render_api_error(exc, title="Stock list unavailable")
    st.caption(
        f"{len(selection['symbols'])} stocks · {settings['interval']} candles · "
        f"{settings['period']} history"
    )
    if backtest:
        st.caption(
            "₹1,00,000 available · ₹0 fixed reserve · up to 3 positions. "
            "Strategy risk limits and costs apply."
        )
    if settings["short_borrow_available"]:
        st.caption(
            "This selected historical short strategy assumes borrow "
            "availability. No broker orders are submitted."
        )
    allowed = authorized and bool(selection["symbols"])
    if backtest:
        left, right = st.columns(2)
        scan = left.button(
            "Scan stocks", disabled=not allowed, key=key + "_scan", width="stretch"
        )
        run = right.button(
            "Backtest",
            disabled=not allowed,
            key=key + "_run",
            type="primary",
            width="stretch",
        )
    else:
        scan = st.button(
            "Scan stocks",
            disabled=not allowed,
            key=key + "_scan",
            type="primary",
            width="stretch",
        )
        run = False
    if not authorized:
        st.info("An Admin API Key is required to start research batches.")
    if selection.get("stale"):
        st.caption("Using the last validated stock-list membership.")
    if scan or run:
        st.session_state.pop(key + "_batch", None)
        kind = "backtest" if run else "scan"
        try:
            batch = submit_research(client, settings, selection, kind)
            st.session_state[key + "_batch"] = batch
        except ApiError as exc:
            render_api_error(exc, title="Research batch could not start")
    batch = st.session_state.get(key + "_batch")
    if batch:
        st.success(
            f"Batch {batch['batch_id']} submitted. Progress and reports are on Reports."
        )
    else:
        st.caption(
            "Batches continue on the backend. Reports are generated "
            "automatically when each run completes."
        )
