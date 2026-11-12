"""Clean research controls; run state and detailed reports live on Reports."""

import streamlit as st

from config.nifty_universes import NIFTY_UNIVERSES
from core.deployment_role import on_render
from scanner.strategy_horizons import horizon_strategies
from scanner.technical_strategy import strategy_profile
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
            "period": settings["period"],
            **(
                {"strategy_ids": settings["strategy_ids"]}
                if settings.get("strategy_ids")
                else {}
            ),
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
    if on_render():
        st.caption(
            "Research runs continue on the cloud server while this page is closed. "
            "Reports shows the actual storage source and durability."
        )
    index = st.selectbox("Stock list", list(NIFTY_UNIVERSES), key=key + "_stocks")
    peers = [
        row["strategy_id"]
        for row in horizon_strategies(settings["horizon"]).values()
        if row["short_borrow_available"] == settings["short_borrow_available"]
    ]
    if len(peers) > 1 and st.toggle(
        "Batch strategies in this horizon", key=key + "_strategy_batch"
    ):
        settings = {**settings, "strategy_ids": peers}
        st.caption(
            f"{len(peers)} strategies will run sequentially, with the same "
            "direction and borrow assumption as this selection."
        )
    if backtest:
        profile = strategy_profile(settings["mode"])
        period = st.selectbox(
            "Backtesting period",
            profile.allowed_periods,
            index=profile.allowed_periods.index(profile.default_period),
            key=key + "_period_" + settings["mode"],
        )
        settings = {**settings, "period": period}
    scope = (
        settings["horizon"],
        settings["strategy_id"],
        index,
        settings["period"],
        tuple(settings.get("strategy_ids", [])),
    )
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
    if settings["interval"] == "1wk":
        st.caption(
            "Weekly gap recovery · Volume EMA30 · Yearly Floor R2. "
            "Signals confirm after the Monday–Sunday week ends in IST; daily "
            "candles handle next-session entries and protective exits. "
            "Up to five years of history supplies the 100-week warm-up. "
            "Scanner/backtest research only."
        )
    if backtest:
        st.caption(
            "The period is requested history. Reports disclose the actual common "
            "date range; limited stock history can shorten the simulation."
        )
        st.caption(
            "₹1,00,000 available · ₹0 fixed reserve · up to 3 positions. "
            "Strategy risk limits and costs apply."
        )
    st.caption(
        "Render divides large runs into bounded, sequential stock/strategy batches. "
        "Each child backtest is an independent portfolio; its returns cannot be "
        "summed into a full-universe account return. Reports keeps the batch index "
        "and each child's detailed report."
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
        st.info("The operator must configure API authentication on the server.")
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
        if batch.get("partition_count", 1) > 1:
            st.info(
                f"{batch['partition_count']} independent stock/strategy batches "
                "are queued sequentially."
            )
    else:
        st.caption(
            "Batches continue on the backend. Reports are generated "
            "automatically when each run completes."
        )
