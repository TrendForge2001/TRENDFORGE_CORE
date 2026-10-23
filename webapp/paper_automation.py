"""Saved-strategy automation controls within the existing paper tab."""

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.paper_excel import strategy_paper_xlsx
from webapp.runtime import admin_key_configured
from webapp.ui import render_api_error


@st.fragment(run_every=15)
def render_paper_automation(client):
    st.subheader("Saved-strategy paper automation")
    st.caption(
        "Shared paper capital; one position per symbol. "
        "Entries require validation, risk approval and a fresh Kite quote. "
        "Turning OFF stops new automated entries; existing positions remain monitored. "
        "Restart requires turning ON again."
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
            st.warning("Entry blockers: " + ", ".join(state["blockers"]))
        if state.get("last_error"):
            st.warning(state["last_error"])
        if state.get("worker_running") is not True:
            st.warning(
                "The automation worker is stopped. Turning ON alone cannot run scans "
                "until the backend worker is available."
            )
        with st.form("saved_strategy_automation_control"):
            enabled = st.toggle(
                "Automate all saved strategies",
                value=state["enabled"],
                disabled=not admin_key_configured(),
            )
            apply = st.form_submit_button(
                "Apply automation switch", disabled=not admin_key_configured()
            )
        if apply:
            try:
                client.put_json("/paper/automation", {"enabled": enabled})
                st.rerun()
            except ApiError as exc:
                render_api_error(exc, title="Automation switch was not saved")
        with st.expander("Strategy eligibility and latest cycle"):
            st.dataframe(
                pd.DataFrame(state.get("strategies", [])),
                hide_index=True,
                use_container_width=True,
            )
            st.json(state.get("last_cycle", {}))
    # Available independently of status/readiness so a read failure cannot hide OFF.
    if st.button("Stop automated paper entries", disabled=not admin_key_configured()):
        try:
            client.put_json("/paper/automation", {"enabled": False})
            st.rerun()
        except ApiError as exc:
            render_api_error(
                exc, title="Automation stop unavailable; activate the paper kill switch"
            )

    st.subheader("P&L by saved strategy")
    period = st.selectbox(
        "Strategy statement period", ["daily", "weekly", "monthly", "yearly", "all"]
    )
    try:
        statement = client.get_json("/paper/strategy-pnl", params={"period": period})
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
        st.dataframe(pd.DataFrame(summary), hide_index=True, use_container_width=True)
        selected = st.selectbox(
            "Strategy statement",
            [row["strategy_id"] for row in rows],
            format_func=lambda key: next(
                row["strategy_name"] for row in rows if row["strategy_id"] == key
            ),
        )
        row = next(row for row in rows if row["strategy_id"] == selected)
        st.dataframe(
            pd.DataFrame(row["closed_trades"]),
            hide_index=True,
            use_container_width=True,
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
            "Strategy accounting is incomplete; totals and export are unavailable."
        )
