"""Owner controls for public holdings and actual trade disclosures."""

import json

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.ui import render_api_error


def render_public_sources(client):
    with st.expander("Fetch Big Shark data from public sources", expanded=False):
        st.caption(
            "Moneycontrol provides reported holdings and quarterly changes. "
            "NSE bulk or block deals provide actual disclosed trade quantities. "
            "Only the latter can update your Activity Signal. Your private "
            "portfolio is never uploaded to these sites."
        )
        try:
            state = client.get_json("/institutional/big-shark/sources")
        except ApiError as exc:
            render_api_error(exc, title="Public source status unavailable")
            return
        config = state.get("config", {})
        st.write("Source refresh:", state.get("status", "not_refreshed"))
        if state.get("checked_at"):
            st.caption("Last attempt: " + state["checked_at"])
        if state.get("failures"):
            st.warning(
                "Some sources could not be refreshed. Last good data remains "
                "available with its original date: "
                + ", ".join(
                    f"{source}: {code}" for source, code in state["failures"].items()
                )
            )
        with st.form("tf_big_shark_public_sources"):
            source = st.selectbox(
                "Actual disclosure feed",
                ("NSE_BULK", "NSE_BLOCK"),
                index=1 if config.get("source") == "NSE_BLOCK" else 0,
                help=(
                    "Bulk and block reports are compared separately "
                    "to avoid overlapping totals."
                ),
            )
            metric = st.selectbox(
                "Public trade comparison",
                ("quantity", "value"),
                index=1 if config.get("metric") == "value" else 0,
                format_func=lambda value: (
                    "Shares" if value == "quantity" else "INR value"
                ),
            )
            start = st.date_input(
                "Public disclosure window start (optional)", value=None
            )
            end = st.date_input("Public disclosure window end (optional)", value=None)
            aliases = st.text_area(
                "Public investor aliases (verified exact names only)",
                value=json.dumps(config.get("aliases", {}), indent=2),
            )
            automatic = st.checkbox(
                "Refresh public feeds daily, even when this page is closed",
                value=config.get("enabled", False),
                help=(
                    "Daily refresh uses the latest seven calendar days; "
                    "failed requests retry after an hour."
                ),
            )
            refresh = st.form_submit_button(
                "Fetch latest Big Shark data", type="primary"
            )
            save = st.form_submit_button("Save public feed schedule")
        if refresh or save:
            try:
                verified = json.loads(aliases)
                if not isinstance(verified, dict):
                    raise ValueError("Aliases must be an object")
                settings = {
                    "enabled": automatic,
                    "source": source,
                    "metric": metric,
                    "investor_aliases": verified,
                }
                if refresh:
                    request = {
                        "source": source,
                        "metric": metric,
                        "investor_aliases": verified,
                    }
                    if start:
                        request["period_start"] = start.isoformat()
                    if end:
                        request["period_end"] = end.isoformat()
                    with st.spinner("Fetching public portfolio and trade disclosures…"):
                        result = client.post_json(
                            "/institutional/big-shark/sources/refresh",
                            request,
                            timeout=180,
                        )
                    if result.get("status") == "unavailable":
                        st.error(
                            "Public data is unavailable. Review the source status "
                            "and retry later."
                        )
                    else:
                        st.success(
                            "Public data refreshed. Activity uses matching "
                            "disclosed trades only."
                        )
                    st.session_state.pop("tf_big_shark_filter_snapshot", None)
                client.put_json("/institutional/big-shark/sources/config", settings)
                st.rerun()
            except (ValueError, TypeError):
                st.error("Supply a JSON object of verified investor aliases.")
            except ApiError as exc:
                render_api_error(exc, title="Public source refresh did not complete")
        holdings = state.get("holdings", {})
        if holdings:
            st.markdown("**Moneycontrol reported holdings changes**")
            st.caption(
                "Moneycontrol quarter: "
                f"{holdings.get('reporting_period') or 'Unknown'} · "
                f"Fetched: {holdings.get('fetched_at', 'Unknown')} · "
                f"Matched visible rows: {holdings.get('matched_rows', 0)} / "
                f"{holdings.get('public_rows', 0)}. "
                "This public page does not establish complete portfolio coverage."
            )
            if holdings.get("period_status") != "COMPLETED_QUARTER":
                st.warning(
                    "The source quarter is open, future-dated or unknown. "
                    "These rows are unverified holdings evidence and cannot "
                    "generate trade activity."
                )
            st.dataframe(
                pd.DataFrame(holdings.get("rows", [])), hide_index=True, width="stretch"
            )
            st.link_button(
                "Open Moneycontrol source",
                "https://www.moneycontrol.com/india-investors-portfolio/top-stocks-bought-sold",
            )
            if holdings.get("investors"):
                st.markdown("**Moneycontrol investor summaries — visible catalogue**")
                st.dataframe(
                    pd.DataFrame(holdings["investors"]),
                    hide_index=True,
                    width="stretch",
                )
        trades = state.get("trades", {})
        if trades:
            st.caption(
                f"{trades.get('source')}: {trades.get('matched_records', 0)} matched / "
                f"{trades.get('records_received', 0)} reported records · "
                f"Coverage: {trades.get('coverage')} · "
                f"Actual window: {trades.get('actual_start')} to "
                f"{trades.get('actual_end')}. "
                "Publication time remains Unknown unless the source supplies it."
            )
            st.link_button(
                "Open NSE disclosure source",
                "https://www.nseindia.com/report-detail/display-bulk-and-block-deals",
            )
            if trades.get("unmatched_investors"):
                st.caption("Unmatched public investor names (up to 100):")
                st.dataframe(
                    pd.DataFrame({"Exact source name": trades["unmatched_investors"]}),
                    hide_index=True,
                    width="stretch",
                )
        return state
