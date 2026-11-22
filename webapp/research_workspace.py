"""Clean research controls; run state and detailed reports live on Reports."""

import streamlit as st

from config.stock_lists import resolve_stock_list
from webapp.api_client import ApiError
from webapp.backtest_controls import stock_list
from webapp.horizon_controls import select_horizon_strategy
from webapp.institutional_selector import filter_symbols, selected_signal
from webapp.stock_lists import ROOT_MANAGED, selected_stock_list, stock_list_picker
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
    settings = select_horizon_strategy(
        key=key, default_horizon="long_term" if backtest else "short_term"
    )
    index = (
        selected_stock_list()
        if st.session_state.get(ROOT_MANAGED)
        else stock_list_picker(key=key + "_stocks")
    )
    if resolve_stock_list(index)[1].kind != "equity":
        st.info(
            "Choose an equity constituent list. Index references are "
            "available on Watchlists."
        )
        return
    with st.expander("Run settings & strategy rules"):
        from scanner.strategy_horizons import scanner_horizon_choices
        from scanner.technical_strategy import strategy_profile

        peers = list(
            dict.fromkeys(
                row["strategy_id"]
                for row in scanner_horizon_choices(settings["horizon"]).values()
            )
        )
        if len(peers) > 1 and st.toggle(
            "Batch strategies in this horizon", key=key + "_strategy_batch"
        ):
            settings = {**settings, "strategy_ids": peers}
            st.caption(
                f"{len(peers)} strategies run sequentially "
                "in separate research accounts."
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
            st.caption(
                "₹1,00,000 account · up to 3 positions · approved risk limits "
                "and trading costs. Reports disclose observed coverage and "
                "independent account boundaries."
            )
        if settings["interval"] == "1wk":
            st.caption(
                "Weekly gap recovery · Volume EMA30 · Yearly Floor R2. "
                "Requires 100 completed weeks and complete prior-year pivots. "
                "New listings may lack this history."
            )
        else:
            st.caption(
                "Completed daily candles and approved entry/exit rules. "
                "Indicator warm-up and annual pivot coverage are checked "
                "separately from source failures."
            )
        if settings["strategy_id"] == "tf_daily_vwma20_50_rsi_fibonacci_yearly":
            st.caption(
                "Daily VWMA20/50 + RSI14 + volume SMA20 · yearly Fibonacci "
                "pivot retest and approved conditional exits."
            )
        from webapp.scanner_reference import render_scanner_reference

        if not backtest:
            render_scanner_reference()
    scope = (
        settings["horizon"],
        settings["strategy_id"],
        index,
        settings["period"],
        tuple(settings.get("strategy_ids", [])),
        selected_signal(),
    )
    if st.session_state.get(key + "_scope") != scope:
        st.session_state.pop(key + "_batch", None)
        st.session_state[key + "_scope"] = scope
    selection = {"symbols": [], "index": index}
    try:
        selection = stock_list(client, index)
        selection["symbols"] = filter_symbols(client, selection["symbols"])
    except ApiError as exc:
        render_api_error(exc, title="Stock list unavailable")
    if selected_signal() != "All stocks":
        st.warning(
            "The current institutional snapshot filters today's universe. "
            "Historical tests do not reconstruct institutional timing; "
            "survivorship and look-ahead bias can apply."
        )
    st.caption(
        f"{len(selection['symbols'])} stocks · {settings['interval']} candles · "
        f"{settings['period']} requested history"
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
        st.caption("Using last validated stock-list membership.")
    if scan or run:
        st.session_state.pop(key + "_batch", None)
        try:
            st.session_state[key + "_batch"] = submit_research(
                client, settings, selection, "backtest" if run else "scan"
            )
        except ApiError as exc:
            render_api_error(exc, title="Research batch could not start")
    batch = st.session_state.get(key + "_batch")
    if batch:
        st.success("Run submitted. Progress, evidence and downloads are on Reports.")
        from webapp.scanner_results import render_batch_results

        render_batch_results(client, batch["batch_id"])
    else:
        st.info(
            "Choose a strategy and start a run. Completed results remain "
            "available on Reports."
        )
