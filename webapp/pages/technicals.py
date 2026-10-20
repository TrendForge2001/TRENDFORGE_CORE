"""NIFTY 500 technical scanner, paper automation and R71.5 backtesting."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Technical Scanner & Backtesting",
    "NIFTY 500 technical-only intraday and swing scanning using Kite candles, with paper-only auto-entry and R71.5 realistic backtesting.",
    kicker="Technicals",
)

client = api_client(timeout=120)


def safe_get(path: str):
    try:
        return client.get_json(path)
    except ApiError:
        return {}


readiness = safe_get("/technical/readiness")
auto = safe_get("/workspace/technical/auto-status")
paper = safe_get("/paper/readiness")
auto_entry = safe_get("/paper/auto-entry/readiness")

r1, r2, r3, r4, r5 = st.columns(5)
with r1:
    market = readiness.get("market_data")
    market = market if isinstance(market, dict) else {}
    st.metric("Kite", str(market.get("status") or "unknown").upper())
with r2:
    st.metric("Auto scanner", str(auto.get("status") or "unknown").upper())
with r3:
    st.metric("Paper trading", str(paper.get("status") or "unknown").upper())
with r4:
    st.metric("Auto-entry", "ON" if auto_entry.get("enabled") else "OFF")
with r5:
    st.metric("Kill switch", "ON" if paper.get("kill_switch") else "OFF")

info_note(
    "Technical path only: fundamentals/enrichment are excluded. Broker orders remain disabled. Scheduled paper entries use the existing R67.2 risk gate."
)

st.subheader("R72.5.1 Strategy Registry")
registry = safe_get("/technical/strategies")
registry_rows = registry.get("strategies")
registry_rows = registry_rows if isinstance(registry_rows, list) else []
registry_readiness = registry.get("readiness")
registry_readiness = (
    registry_readiness if isinstance(registry_readiness, dict) else {}
)

reg1, reg2, reg3, reg4 = st.columns(4)
with reg1:
    st.metric("Registered", int(registry_readiness.get("strategies") or 0))
with reg2:
    st.metric(
        "Notebook strategies",
        int(registry_readiness.get("user_notebook_strategies") or 0),
    )
with reg3:
    st.metric(
        "Template strategies",
        int(registry_readiness.get("template_strategies") or 0),
    )
with reg4:
    st.metric(
        "Execution wiring",
        "NEXT BATCH"
        if registry_readiness.get("execution_wiring") == "R72.5.2_pending"
        else str(registry_readiness.get("execution_wiring") or "—"),
    )

if registry_rows:
    notebook_tab, template_tab = st.tabs(
        ["Notebook strategies", "Template strategies"]
    )

    def render_registry_table(source: str) -> None:
        rows = [
            row for row in registry_rows
            if str(row.get("source") or "") == source
        ]
        if not rows:
            st.info("No strategies registered for this source.")
            return
        frame = pd.DataFrame(rows)
        columns = [
            "strategy_id",
            "name",
            "family",
            "modes",
            "default_interval",
            "paper_eligible",
            "implementation_status",
        ]
        st.dataframe(
            frame[[column for column in columns if column in frame.columns]],
            use_container_width=True,
            hide_index=True,
        )

    with notebook_tab:
        render_registry_table("user_notebook")
    with template_tab:
        render_registry_table("template")

    labels = {
        f"{row.get('name')} · {row.get('strategy_id')}": row
        for row in registry_rows
    }
    selected_label = st.selectbox(
        "Inspect strategy definition",
        list(labels),
        key="tf_strategy_registry_selection",
    )
    selected = labels[selected_label]
    with st.expander("Strategy details", expanded=False):
        st.markdown(f"**{selected.get('name')}**")
        st.caption(str(selected.get("description") or ""))
        st.json(
            {
                "strategy_id": selected.get("strategy_id"),
                "source": selected.get("source"),
                "family": selected.get("family"),
                "modes": selected.get("modes"),
                "intervals": selected.get("intervals"),
                "universes": selected.get("universes"),
                "indicators": selected.get("indicators"),
                "entry_rules": selected.get("entry_rules"),
                "exit_rules": selected.get("exit_rules"),
                "target_rules": selected.get("target_rules"),
                "stoploss_rules": selected.get("stoploss_rules"),
                "risk_rules": selected.get("risk_rules"),
                "notes": selected.get("notes"),
                "ambiguities": selected.get("ambiguities"),
                "paper_eligible": selected.get("paper_eligible"),
                "implementation_status": selected.get(
                    "implementation_status"
                ),
            }
        )
else:
    st.caption("Strategy registry is unavailable from the backend.")

st.subheader("R72.5.2 Multi-Strategy NIFTY Scanner")
multi_ready = safe_get("/technical/multi-strategy/readiness")
multi_status = safe_get("/technical/multi-strategy/status")
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Engine", str(multi_ready.get("version") or "—"))
with m2:
    engine_meta = multi_ready.get("strategy_engine")
    engine_meta = engine_meta if isinstance(engine_meta, dict) else {}
    st.metric(
        "Executable strategies",
        len(engine_meta.get("executable_strategy_ids") or []),
    )
with m3:
    st.metric(
        "Review required",
        len(engine_meta.get("review_required_strategy_ids") or []),
    )
with m4:
    st.metric("Scanner", str(multi_status.get("status") or "idle").upper())

st.caption(
    "Scanner-only validation path: NIFTY 100/200/500 · Kite candles · no paper orders · no broker orders."
)

ms1, ms2, ms3, ms4 = st.columns(4)
with ms1:
    multi_universe = st.selectbox(
        "Universe",
        ["NIFTY 100", "NIFTY 200", "NIFTY 500"],
        key="tf_r7252_universe",
    )
with ms2:
    multi_mode = st.selectbox(
        "Mode",
        ["swing", "intraday", "positional"],
        key="tf_r7252_mode",
    )
with ms3:
    multi_source_label = st.selectbox(
        "Strategy source",
        ["All", "Notebook", "Template"],
        key="tf_r7252_source",
    )
with ms4:
    multi_top_n = st.number_input(
        "Top picks",
        min_value=5,
        max_value=100,
        value=20,
        step=5,
        key="tf_r7252_topn",
    )

source_map = {
    "All": "all",
    "Notebook": "user_notebook",
    "Template": "template",
}
multi_limit_full = st.toggle(
    "Scan full selected universe",
    value=True,
    key="tf_r7252_full",
)
multi_limit = None
if not multi_limit_full:
    multi_limit = st.number_input(
        "Staged symbol limit",
        min_value=1,
        max_value=500,
        value=25,
        step=25,
        key="tf_r7252_limit",
    )

start_multi = st.button(
    "Start R72.5.2 Multi-Strategy Scan",
    use_container_width=True,
    disabled=bool(multi_status.get("busy")),
)
if start_multi:
    if not admin_key_configured():
        st.error("Admin API Key is required to start the scanner.")
    else:
        payload = {
            "universe": multi_universe,
            "mode": multi_mode,
            "source": source_map[multi_source_label],
            "top_n": int(multi_top_n),
            "limit": int(multi_limit) if multi_limit is not None else None,
            "force_refresh_universe": False,
        }
        try:
            response = client.post_json(
                "/technical/multi-strategy/run",
                payload,
                timeout=30,
            )
            st.success(
                f"R72.5.2 scan {response.get('status', 'started')} · "
                f"{response.get('run_id', '')}"
            )
            st.rerun()
        except ApiError as exc:
            render_api_error(exc, title="Multi-strategy scan start failed")

multi_status = safe_get("/technical/multi-strategy/status")
active = multi_status.get("active_request")
active = active if isinstance(active, dict) else {}
if multi_status.get("busy"):
    st.info(
        "Multi-strategy scan is running"
        + (f" · {active.get('universe')} · {active.get('mode')}" if active else "")
    )

multi_result = multi_status.get("last_result")
multi_result = multi_result if isinstance(multi_result, dict) else {}
if multi_result:
    mr1, mr2, mr3, mr4 = st.columns(4)
    with mr1:
        st.metric("Completed", int(multi_result.get("completed_symbols") or 0))
    with mr2:
        st.metric("Errors", int(multi_result.get("error_symbols") or 0))
    with mr3:
        st.metric("Candidates", int(multi_result.get("candidate_symbols") or 0))
    with mr4:
        st.metric("Strong BUY", int(multi_result.get("strong_buy_symbols") or 0))

    multi_picks = multi_result.get("top_picks")
    multi_picks = multi_picks if isinstance(multi_picks, list) else []
    if multi_picks:
        frame = pd.DataFrame(multi_picks)
        columns = [
            "symbol",
            "consensus",
            "consensus_score",
            "buy_strategy_count",
            "notebook_buy_count",
            "template_buy_count",
            "bullish_confirmation_count",
            "primary_strategy_id",
            "bar_at",
        ]
        st.dataframe(
            frame[[column for column in columns if column in frame.columns]],
            use_container_width=True,
            hide_index=True,
        )
        selected_symbol = st.selectbox(
            "Inspect multi-strategy evidence",
            [str(item.get("symbol")) for item in multi_picks],
            key="tf_r7252_pick",
        )
        selected_pick = next(
            (
                item
                for item in multi_picks
                if str(item.get("symbol")) == selected_symbol
            ),
            None,
        )
        if selected_pick:
            with st.expander("Matched strategy evidence", expanded=False):
                st.json(selected_pick)

    with st.expander("Per-strategy scan summary", expanded=False):
        strategy_summary = multi_result.get("strategy_summary")
        strategy_summary = (
            strategy_summary
            if isinstance(strategy_summary, list)
            else []
        )
        if strategy_summary:
            st.dataframe(
                pd.DataFrame(strategy_summary),
                use_container_width=True,
                hide_index=True,
            )

st.subheader("Tomorrow automation")
schedule_cols = st.columns(4)
with schedule_cols[0]:
    st.metric("Universe", str(auto.get("universe") or "NIFTY 500"))
with schedule_cols[1]:
    st.metric("Swing scan", str(auto.get("swing_time_ist") or "09:25") + " IST")
with schedule_cols[2]:
    st.metric(
        "Intraday window",
        f"{auto.get('intraday_start_ist') or '09:30'}–{auto.get('intraday_end_ist') or '14:45'}",
    )
with schedule_cols[3]:
    st.metric("Auto paper", "ON" if auto.get("paper_execution") else "OFF")

if auto.get("status") == "disabled":
    st.warning("Automatic technical scanning is disabled in the backend environment.")

st.subheader("Manual NIFTY 500 scanner")
manual_paper = st.toggle(
    "Allow approved paper entries for this manual scan",
    value=False,
    help="Still subject to paper auto-entry score/confidence, RR, capital, daily-loss, position-count and market-hours gates.",
)
b1, b2, b3 = st.columns(3)
with b1:
    run_intraday = st.button(
        "Run NIFTY 500 Intraday",
        type="primary",
        use_container_width=True,
    )
with b2:
    run_swing = st.button(
        "Run NIFTY 500 Swing",
        use_container_width=True,
    )
with b3:
    refresh = st.button("Refresh status", use_container_width=True)

if run_intraday or run_swing:
    if not admin_key_configured():
        st.error("Enter the Admin API Key at sign-in or System session state first.")
    else:
        mode = "intraday" if run_intraday else "swing"
        try:
            response = client.post_json(
                "/workspace/technical/run",
                {
                    "mode": mode,
                    "execute_paper": bool(manual_paper),
                },
                timeout=30,
            )
            st.success(
                f"{mode.title()} NIFTY 500 scan: {response.get('status', 'started')}."
            )
            st.rerun()
        except ApiError as exc:
            render_api_error(exc, title="Technical scan start failed")

if refresh:
    st.rerun()

auto = safe_get("/workspace/technical/auto-status")
last = auto.get("last_results")
last = last if isinstance(last, dict) else {}
for mode in ("intraday", "swing"):
    result = last.get(mode)
    if not isinstance(result, dict):
        continue
    st.markdown(f"**Latest {mode.title()} run**")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Completed", int(result.get("completed_symbols") or 0))
    with c2:
        st.metric("Errors", int(result.get("error_symbols") or 0))
    with c3:
        st.metric("BUY candidates", int(result.get("buy_candidates") or 0))
    with c4:
        p = result.get("paper")
        p = p if isinstance(p, dict) else {}
        st.metric("Paper", str(p.get("status") or "n/a").upper())
    picks = result.get("top_picks")
    picks = picks if isinstance(picks, list) else []
    if picks:
        frame = pd.DataFrame(picks)
        preferred = [
            "symbol", "score", "confidence", "trigger",
            "entry", "stoploss", "target2", "reward_risk",
        ]
        st.dataframe(
            frame[[c for c in preferred if c in frame.columns]],
            use_container_width=True,
            hide_index=True,
        )

st.divider()
st.subheader("R71.5 NIFTY 100 / 200 / 500 realistic backtesting")
st.caption(
    "Runs both swing and intraday realistic backtests with ATR stop/target logic, costs/slippage, and 15:00 IST intraday exit. The export contains the P&L workbook."
)

validation = safe_get("/technical/validation/status")
v1, v2, v3 = st.columns(3)
with v1:
    st.metric("Validation", str(validation.get("status") or "not started").upper())
with v2:
    progress = validation.get("progress")
    progress = progress if isinstance(progress, dict) else {}
    st.metric("Phase", str(progress.get("phase") or "—"))
with v3:
    st.metric("Run ID", str(validation.get("run_id") or "—"))

run_validation = st.button(
    "Run NIFTY 100/200/500 Backtesting",
    use_container_width=True,
)
if run_validation:
    if not admin_key_configured():
        st.error("Admin API Key is required to initiate the batch backtest.")
    else:
        try:
            response = client.post_json(
                "/technical/validation/run",
                {
                    "capital": 100000.0,
                    "chunk_size": 25,
                    "force": False,
                },
                timeout=30,
            )
            token = response.get("export_token")
            if token:
                st.session_state["tf_r715_export_token"] = token
            st.success(
                f"Validation {response.get('status', 'started')} · {response.get('run_id', '')}"
            )
            st.rerun()
        except ApiError as exc:
            render_api_error(exc, title="Backtest validation start failed")

token = str(st.session_state.get("tf_r715_export_token") or "").strip()
if token:
    try:
        workbook = client.get_bytes(
            "/technical/validation/export",
            params={"token": token},
            timeout=120,
        )
        st.download_button(
            "Download R71.5 P&L Excel",
            data=workbook,
            file_name="TrendForge_R71_5_NIFTY_Technical_PnL.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except ApiError:
        st.caption("P&L workbook becomes available after the validation run completes.")
