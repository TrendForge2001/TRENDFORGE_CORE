"""Live paper status refreshes independently of manual-entry form editing."""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from core.deployment_role import cloud_read_only
from webapp.api_client import ApiError
from webapp.paper_automation import render_paper_automation
from webapp.paper_policy import paper_entry_allowed, render_paper_entry_policy
from webapp.paper_trade_reports import render_trade_reports
from webapp.runtime import admin_key_configured
from webapp.trade_table import trade_frame
from webapp.ui import render_api_error
from webapp.workspace_layout import workspace_panels


@st.fragment(run_every=15)
def render_live_paper_workspace(client):
    st.caption(
        "Refreshes every 15 seconds while this page is open. "
        "Backend monitoring continues independently."
    )
    controls, results_panel = workspace_panels("paper")
    if cloud_read_only():
        results_panel.caption(
            "Render ledger only. PC positions and P&L are unavailable here; "
            "zero cloud positions does not mean the PC has zero positions."
        )
    with controls:
        if st.button("Refresh paper readiness & positions"):
            st.rerun()
        paper_view = (
            st.segmented_control(
                "Paper view",
                ["Open positions", "Trade reports", "Strategy readiness"],
                default="Open positions",
                key="tf_paper_view",
            )
            or "Open positions"
        )
        st.caption("Closed fills and downloads are under Trade reports.")
        portfolio = None
        snapshot = None
        readiness = {}
        try:
            snapshot = client.get_json(
                "/paper/trade-reports",
                params={
                    "period": (st.session_state.get("tf_paper_report_period") or "all")
                    if paper_view == "Trade reports"
                    else "daily"
                },
            )
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
            "P&L uses last saved position marks; monitor success does not "
            "confirm quote freshness."
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
        if paper_view == "Trade reports":
            render_trade_reports(client, report=snapshot)
        elif paper_view == "Open positions":
            st.subheader("Paper portfolio — open positions")
            if positions is None:
                st.info(
                    "Paper positions are unavailable until the portfolio can be loaded."
                )
            elif positions:
                st.dataframe(trade_frame(positions), width="stretch")
                st.caption(
                    "OPEN/CLOSE PRICE are trade entry/exit prices. LTP is the saved "
                    "position mark. Open-position realised P&L and sell/buy values "
                    "include any partial exit fills. NSE/EQ is this app's equity book."
                )
            else:
                st.info(
                    "No open paper positions. Closed fills remain in Trade reports."
                )

    with controls:
        render_paper_automation(
            client,
            results=results_panel,
            view="Validation"
            if paper_view == "Strategy readiness"
            else "Open positions",
        )

    st.caption(
        "Page refreshed: "
        + datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y · %H:%M:%S IST")
    )
    return can_enter
