"""Saved-strategy automation controls within the existing paper tab."""

from contextlib import nullcontext

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.market_colours import market_frame
from webapp.paper_excel import strategy_paper_xlsx
from webapp.paper_policy import render_paper_storage_setup
from webapp.runtime import admin_key_configured
from webapp.trade_timestamps import format_trade_frame
from webapp.ui import render_api_error


def render_paper_automation(client, *, results=None, view=None):
    st.subheader("Automated paper trading")
    st.caption(
        "Start admits validated BUY/SELL entries with fresh quotes. "
        "Stop blocks entries; monitored exits continue. Restart resets to OFF."
    )
    state = None
    try:
        state = client.get_json("/paper/automation")
        if type(state.get("enabled")) is not bool:
            raise ApiError("Invalid automation status")
    except ApiError as exc:
        state = None
        render_api_error(exc, title="Automation status unavailable")
    if state is not None:
        st.caption(
            f"Automation: {'ON' if state['enabled'] else 'OFF'} · "
            f"{state.get('phase', 'unavailable')}"
        )
        if state.get("resume_required"):
            st.warning(
                "Automation was requested before restart. "
                "Review readiness and turn ON to resume."
            )
        if state.get("blockers"):
            labels = {
                "persistent_storage_required": (
                    "Persistent disk or restart verification is missing"
                ),
                "paper_runtime_not_ready": (
                    "Paper entries are waiting for readiness checks"
                ),
            }
            st.warning(
                "Entry blockers: "
                + "; ".join(labels.get(code, code) for code in state["blockers"])
            )
        render_paper_storage_setup(state.get("storage_setup"))
        if state.get("last_error"):
            st.warning(state["last_error"])
        if state.get("worker_running") is not True:
            st.warning(
                "The automation worker is stopped. Turning ON alone cannot run scans "
                "until the backend worker is available."
            )
        st.caption("Paper universe: " + str(state.get("universe") or "NIFTY 500"))
        if state.get("universe") not in {None, "NIFTY 500"}:
            st.warning(
                "The saved paper universe is not NIFTY 500. Stop automation, "
                "then Start to use NIFTY 500 with the saved stock/strategy filters."
            )
        if state.get("target_symbols"):
            st.caption(
                "Target stocks: "
                + ", ".join(state["target_symbols"])
                + " · "
                + str(state.get("universe"))
            )
        else:
            st.caption("Stock scope: scan the full paper universe for fresh entries.")
        strategies = state.get("strategies", [])
        target_ids = state.get("target_strategy_ids")
        selected = [
            row
            for row in strategies
            if (target_ids is None and row.get("paper_eligible"))
            or (target_ids is not None and row.get("strategy_id") in target_ids)
        ]
        st.caption(
            "Selected strategies: "
            + (
                "; ".join(row.get("name", row["strategy_id"]) for row in selected)
                if len(selected) <= 2
                else f"{len(selected)} eligible strategy/scanner pairs"
            )
        )
        if len(selected) > 2:
            with st.expander("View selected scanner / strategy pairs"):
                for row in selected:
                    st.write(row.get("name", row["strategy_id"]))
        st.caption(
            "Each entry requires a new matching scan, passed validation, "
            "a fresh quote and risk approval. Selection alone does not open a trade."
        )
        can_start = (
            admin_key_configured()
            and not state["enabled"]
            and not state.get("blockers")
            and state.get("worker_running") is True
        )
        if st.button(
            "Start automated paper trading",
            type="primary",
            disabled=not can_start,
            key="paper_automation_start",
        ):
            try:
                payload = {"enabled": True, "universe": "NIFTY 500"}
                if state.get("target_symbols") is not None:
                    payload["symbols"] = state["target_symbols"]
                if state.get("target_strategy_ids") is not None:
                    payload["strategy_ids"] = state["target_strategy_ids"]
                client.put_json("/paper/automation", payload)
                st.rerun()
            except ApiError as exc:
                render_api_error(exc, title="Paper trading could not start")
        if view in {None, "Validation"}:
            with (
                results if results is not None else nullcontext(),
                st.expander("Strategy eligibility and latest cycle"),
            ):
                st.dataframe(
                    format_trade_frame(pd.DataFrame(state.get("strategies", []))),
                    hide_index=True,
                    width="stretch",
                )
                st.json(state.get("last_cycle", {}))
    # Available independently of status/readiness so a read failure cannot hide OFF.
    if st.button(
        "Stop automated paper trading",
        disabled=not admin_key_configured(),
        key="paper_automation_stop",
    ):
        try:
            client.put_json("/paper/automation", {"enabled": False})
            st.rerun()
        except ApiError as exc:
            render_api_error(
                exc, title="Automation stop unavailable; activate the paper kill switch"
            )

    if state is not None:
        with results if results is not None else nullcontext():
            render_execution_diagnostics(state)

    with st.expander("Prepare strategy validation before the session"):
        st.caption(
            "Run historical validation for the full paper universe before market open. "
            "This prepares evidence; it does not arm automation or place orders. "
            "A strategy that fails validation remains blocked."
        )
        if st.button("Validate saved strategies", disabled=not admin_key_configured()):
            try:
                client.post_json(
                    "/technical/multi-strategy/validation/run",
                    {
                        "universes": ["NIFTY 500"],
                        "modes": ["intraday", "swing", "positional"],
                        "source": "all",
                        "limit": None,
                    },
                    timeout=60,
                )
                st.success(
                    "Validation requested. Use Check validation progress; "
                    "automation stays under your Start/Stop control."
                )
            except ApiError as exc:
                render_api_error(exc, title="Validation could not start")
        if st.button("Check validation progress", disabled=not admin_key_configured()):
            try:
                report = client.get_json("/technical/multi-strategy/validation/status")
                st.caption("Validation: " + str(report.get("status", "unavailable")))
                with results if results is not None else nullcontext():
                    st.dataframe(
                        pd.DataFrame(report.get("strategy_validation") or []),
                        hide_index=True,
                        width="stretch",
                    )
            except ApiError as exc:
                render_api_error(exc, title="Validation progress unavailable")

    if view in {None, "Strategy P&L"}:
        with st.expander("P&L by saved strategy", expanded=view == "Strategy P&L"):
            st.subheader("P&L by saved strategy")
            period = st.selectbox(
                "Strategy statement period",
                ["daily", "weekly", "monthly", "yearly", "all"],
            )
            try:
                statement = client.get_json(
                    "/paper/strategy-pnl", params={"period": period}
                )
                # Validate before displaying/exporting financial totals.
                workbook = strategy_paper_xlsx(statement)
                rows = statement["rows"]
                st.caption(statement["accounting"])
                summary = [
                    {
                        key: row[key]
                        for key in (
                            "strategy_id",
                            "strategy_name",
                            "trade_count",
                            "open_count",
                            "realized_pnl",
                            "unrealized_pnl",
                            "total_pnl",
                        )
                    }
                    for row in rows
                ]
                with results if results is not None else nullcontext():
                    st.dataframe(
                        market_frame(format_trade_frame(pd.DataFrame(summary))),
                        hide_index=True,
                        width="stretch",
                    )
                selected = st.selectbox(
                    "Strategy statement",
                    [row["strategy_id"] for row in rows],
                    format_func=lambda key: next(
                        row["strategy_name"]
                        for row in rows
                        if row["strategy_id"] == key
                    ),
                )
                row = next(row for row in rows if row["strategy_id"] == selected)
                with results if results is not None else nullcontext():
                    st.dataframe(
                        market_frame(
                            format_trade_frame(pd.DataFrame(row["closed_trades"]))
                        ),
                        hide_index=True,
                        width="stretch",
                    )
                st.download_button(
                    "Download selected strategy P&L (.xlsx)",
                    strategy_paper_xlsx(statement, selected),
                    file_name=f"trendforge_{selected}_{period}.xlsx",
                )
                st.download_button(
                    "Download all strategy P&L (.xlsx)",
                    workbook,
                    file_name=f"trendforge_all_strategies_{period}.xlsx",
                )
            except ApiError as exc:
                render_api_error(exc, title="Strategy P&L unavailable")
            except (KeyError, ValueError, TypeError, ImportError):
                st.error(
                    "Strategy accounting is incomplete; "
                    "totals and export are unavailable."
                )


def render_execution_diagnostics(state: dict) -> None:
    st.subheader("Paper execution diagnostics")
    validation = state.get("validation") or {}
    cycle = state.get("last_cycle") or {}
    if validation:
        st.caption(
            "Validation: "
            + str(validation.get("status", "unavailable"))
            + " · "
            + str((validation.get("progress") or {}).get("phase", ""))
        )
    if not cycle:
        st.info(
            "No entry cycle recorded in this process yet. Current phase: "
            + str(state.get("phase", "unavailable"))
            + ". Review validation progress and entry blockers."
        )
        return
    st.caption(
        "Last recorded cycle: "
        + str(cycle.get("checked_at", "unavailable"))
        + " · "
        + str(cycle.get("entry_status", "see strategy outcomes"))
        + ". The worker's ON status does not prove a paper fill."
    )
    scans = cycle.get("scans") or []
    if scans:
        st.dataframe(
            market_frame(pd.DataFrame(scans)), hide_index=True, width="stretch"
        )
    rows = []
    names = {
        row["strategy_id"]: row.get("name", row["strategy_id"])
        for row in state.get("strategies", [])
    }
    for row in cycle.get("strategies") or []:
        reasons = list(row.get("blockers") or [])
        for group in row.get("rejections") or []:
            reasons.extend(group)
        rows.append(
            {
                "strategy": names.get(
                    row.get("strategy_id"), row.get("strategy_id", "")
                )
                .replace("Intraday SHORT · ", "")
                .replace("tf_intraday_", ""),
                "status": row.get("status"),
                "scanner_matches": row.get("scanner_matches"),
                "candidates": row.get("candidate_count"),
                "risk_approved": row.get("risk_approved_count"),
                "opened": row.get("opened_count", 0),
                "reason": ", ".join(dict.fromkeys(reasons))
                or (
                    "No matching entry signal"
                    if row.get("status") == "no_candidates"
                    else "See recorded outcome"
                ),
            }
        )
    if rows:
        st.dataframe(
            market_frame(pd.DataFrame(rows)),
            hide_index=True,
            width="stretch",
            column_config={
                "strategy": st.column_config.TextColumn("Strategy", width="medium"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "scanner_matches": st.column_config.NumberColumn(
                    "Matches", width="small"
                ),
                "candidates": st.column_config.NumberColumn(
                    "Candidates", width="small"
                ),
                "risk_approved": st.column_config.NumberColumn(
                    "Approved", width="small"
                ),
                "opened": st.column_config.NumberColumn("Opened", width="small"),
                "reason": st.column_config.TextColumn("Reason", width="medium"),
            },
        )
