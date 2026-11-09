"""Live paper status refreshes independently of manual-entry form editing."""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from core.deployment_role import cloud_read_only
from webapp.api_client import ApiError
from webapp.market_colours import market_frame
from webapp.paper_automation import render_paper_automation
from webapp.paper_policy import paper_entry_allowed, render_paper_entry_policy
from webapp.runtime import admin_key_configured
from webapp.trade_timestamps import format_trade_frame
from webapp.ui import render_api_error
from webapp.workspace_layout import workspace_panels


@st.fragment(run_every=15)
def render_live_paper_workspace(client):
    st.caption(
        "Refreshes every 15 seconds while this page is open. "
        "Backend monitoring continues independently."
    )
    controls, results_panel = workspace_panels("paper")
    with controls:
        if st.button("Refresh paper readiness & positions"):
            st.rerun()
        paper_view = "Open positions"
        st.caption("Statements are on Reports → Paper statements.")
        portfolio = None
        readiness = {}
        try:
            snapshot = client.get_json("/workspace/paper-portfolio")
            candidate = snapshot.get("portfolio")
            if (
                not isinstance(candidate, dict)
                or type(candidate.get("open_positions")) is not int
                or candidate["open_positions"] < 0
                or not isinstance(candidate.get("positions"), list)
                or not all(isinstance(row, dict) for row in candidate["positions"])
                or candidate["open_positions"] != len(candidate["positions"])
                or any(
                    type(candidate.get(key)) not in {int, float}
                    or not math.isfinite(candidate[key])
                    for key in ("unrealized_pnl", "realized_pnl")
                )
            ):
                raise ApiError("Paper portfolio response is incomplete or invalid")
            portfolio = candidate
        except ApiError as exc:
            render_api_error(exc, title="Paper portfolio unavailable")
        try:
            readiness = client.get_json("/paper/readiness")
        except ApiError as exc:
            render_api_error(exc, title="Paper-entry readiness unavailable")

        can_enter = (
            portfolio is not None
            and paper_entry_allowed(readiness)
            and admin_key_configured()
            and not cloud_read_only()
        )
        render_paper_entry_policy(readiness)

        a, b, c, d = results_panel.columns(4)
        a.metric(
            "Open positions",
            portfolio["open_positions"] if portfolio is not None else "Unavailable",
        )
        b.metric(
            "Unrealized P&L (last marks)",
            f"₹{portfolio['unrealized_pnl']:,.2f}"
            if portfolio is not None
            else "Unavailable",
        )
        c.metric(
            "Lifetime realized P&L",
            f"₹{portfolio['realized_pnl']:,.2f}"
            if portfolio is not None
            else "Unavailable",
        )
        d.metric(
            "Kill switch",
            ("ON" if readiness["kill_switch"] else "OFF")
            if type(readiness.get("kill_switch")) is bool
            else "Unavailable",
        )
        monitor = readiness.get("automatic_monitor")
        monitor = monitor if isinstance(monitor, dict) else {}
        results_panel.caption(
            "Unrealized P&L uses the last saved position marks, which can be stale "
            "or reset to entry on restoration. A successful monitor poll does "
            "not establish exchange-quote freshness."
        )
        if not readiness:
            st.warning(
                "Automatic quote-monitor status is unavailable. "
                "Saved P&L marks may be stale."
            )
        elif monitor.get("enabled") is not True or monitor.get("running") is not True:
            st.warning(
                "Automatic quote monitoring is disabled or stopped. Saved P&L marks "
                "may be stale; use the paper quote/SL monitor to update them."
            )
        elif monitor.get("last_error"):
            st.warning(
                "The last automatic quote-monitor attempt failed. "
                "Saved P&L marks may be stale."
            )
        if monitor.get("last_success_at"):
            st.caption(f"Last successful monitor poll: {monitor['last_success_at']}")
    with results_panel:
        positions = portfolio["positions"] if portfolio is not None else None
        st.subheader("Paper portfolio — open positions")
        if positions is None:
            st.info(
                "Paper positions are unavailable until the portfolio can be loaded."
            )
        elif positions:
            st.dataframe(
                market_frame(format_trade_frame(pd.DataFrame(positions))),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No open paper positions.")

    with controls:
        render_paper_automation(client, results=results_panel, view=paper_view)

    st.caption(
        "Page refreshed: "
        + datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y · %H:%M:%S IST")
    )
    return can_enter
