"""Owner-only corrected validation, independent stocks and one shared book."""

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.ui import render_api_error


def render_policy_validation(client):
    try:
        result = client.get_json("/technical/multi-strategy/validation/status")
    except ApiError as exc:
        render_api_error(exc)
        return
    st.subheader("Paper-policy validation")
    st.write(
        "Historical research using the saved paper admission policy. "
        "Paper entries require a separate approved start."
    )
    status = result.get("status", "not_started")
    if result.get("failure_code") == "storage_headroom":
        st.info(
            "Research paused for disk headroom. Completed checkpoints are retained; "
            "performance results are not complete."
        )
    st.caption(
        f"Run status: {status} · "
        f"Registry: {result.get('registry_version', 'Unavailable')}"
    )
    if result.get("registry_current") is False:
        st.info(
            "The saved result uses an earlier calculation version. "
            "A corrected run is required for admission."
        )
    progress = result.get("progress") or {}
    if status == "running":
        st.write(f"Stage: {progress.get('phase', 'starting')}")
        st.progress(min(1.0, max(0.0, float(progress.get("progress_pct", 0)) / 100)))
    policy = result.get("admission_policy") or (result.get("request") or {}).get(
        "admission_policy"
    )
    if policy:
        st.caption(
            f"Account ₹{policy['capital']:,.0f} · "
            f"Maximum {min(3, policy['max_open_positions'])} positions · "
            f"Minimum reward/risk {policy['minimum_rr']}:1 · "
            f"Daily entry limit {policy['max_daily_entries'] or 'Unlimited'}"
        )
        st.caption(
            "Costs are versioned research estimates, including modeled slippage "
            "and applicable estimated delivery charges. "
            "Historical statutory fee schedules are not reconstructed."
        )
    shared = result.get("shared_book_summary") or {}
    if shared:
        st.subheader("One shared ₹1 lakh book")
        if shared.get("status") == "blocked_by_scan_coverage":
            st.info(
                "The shared book could not admit entries because the complete-scan "
                "requirement failed. Zero P&L here is not performance qualification."
            )
        st.caption(
            "All approved strategy pairs share the account over their common "
            "60-day observation window. "
            "This is separate from independent-stock results."
        )
        for column, label, key in zip(
            st.columns(3),
            ("Gross P&L", "Modeled costs", "Net P&L"),
            ("gross_pnl_before_transaction_costs", "transaction_costs", "net_pnl"),
            strict=True,
        ):
            value = shared.get(key)
            column.metric(
                label,
                f"₹{value:,.2f}" if isinstance(value, (int, float)) else "Unavailable",
            )
        st.write(
            f"Trades: {shared.get('total_trades', 0)} · "
            f"Maximum simultaneous positions: {shared.get('max_observed_positions', 0)}"
        )
        if shared.get("rejection_counts"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Rejection reason": key, "Count": value}
                        for key, value in shared["rejection_counts"].items()
                    ]
                ),
                hide_index=True,
            )
    rows = result.get("strategy_universe_metrics") or []
    if rows:
        st.subheader("Independent-stock diagnostic results")
        st.caption(
            "Each stock uses its own test account. "
            "These P&Ls cannot be added to the shared account. "
            "Active-stock figures do not replace full-universe promotion gates."
        )
        fields = (
            "strategy_name",
            "mode",
            "completed_symbols",
            "no_trade_symbols",
            "flat_traded_symbols",
            "loss_making_symbols",
            "profitable_symbols",
            "total_trades",
            "net_pnl",
            "transaction_costs",
            "active_profitable_symbol_pct",
            "profitable_symbol_pct",
        )
        st.dataframe(
            pd.DataFrame([{key: row.get(key) for key in fields} for row in rows]),
            hide_index=True,
        )
        rejections = [
            {
                "Strategy": row.get("strategy_name"),
                "Mode": row.get("mode"),
                "Reason": reason,
                "Count": count,
            }
            for row in rows
            for reason, count in (row.get("admission_rejection_counts") or {}).items()
        ]
        if rejections:
            st.subheader("Rejected historical entries")
            st.dataframe(pd.DataFrame(rejections), hide_index=True)
            samples = [
                {
                    "Strategy": row.get("strategy_name"),
                    "Mode": row.get("mode"),
                    **sample,
                }
                for row in rows
                for sample in row.get("admission_rejection_samples", [])
            ]
            if samples:
                st.caption(
                    "Examples: up to 50 rejection events per strategy/horizon. "
                    "Reason totals above include every rejection. "
                    "The private JSON export retains up to 100 examples per stock."
                )
                st.dataframe(pd.DataFrame(samples), hide_index=True)
