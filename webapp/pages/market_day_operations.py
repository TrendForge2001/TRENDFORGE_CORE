"""Scheduled market-day operations control center."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Market-Day Operations",
    "Control opt-in morning and end-of-day automation, inspect the current NSE session, and audit operational runs without enabling broker orders.",
    kicker="Operations",
)

client = api_client(timeout=920)

try:
    readiness = client.get_json("/operations/readiness")
    session = client.get_json("/operations/session")
    policy_state = client.get_json("/operations/policy")
    control = client.get_json("/operations/control-center")
    history = client.get_json(
        "/operations/runs",
        params={"limit": 50},
    )
except ApiError as exc:
    render_api_error(
        exc,
        title="Market-day operations unavailable",
    )
    st.stop()

info_note(
    "R69.0 automation is disabled by default. The worker is dependency-free and market-day aware; scheduled jobs run only inside their configured grace windows. It never starts a scanner run or places broker orders."
)

policy = policy_state.get("policy")
policy = policy if isinstance(policy, dict) else {}
morning = policy.get("morning")
morning = morning if isinstance(morning, dict) else {}
eod = policy.get("eod")
eod = eod if isinstance(eod, dict) else {}
calendar = policy.get("calendar")
calendar = calendar if isinstance(calendar, dict) else {}

m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.metric(
        "Session",
        str(session.get("phase") or "unknown").upper(),
    )
with m2:
    st.metric(
        "Market day",
        "YES" if session.get("market_day") else "NO",
    )
with m3:
    st.metric(
        "Automation",
        "ON" if policy.get("automation_enabled") else "OFF",
    )
with m4:
    st.metric(
        "Worker",
        str(readiness.get("status") or "unknown").upper(),
    )
with m5:
    st.metric(
        "Morning",
        str(morning.get("time_ist") or "08:45"),
    )
with m6:
    st.metric(
        "EOD",
        str(eod.get("time_ist") or "15:45"),
    )

st.caption(
    f"{session.get('weekday') or 'Unknown day'} · "
    f"{session.get('date_ist') or 'unknown date'} · "
    f"calendar: {session.get('calendar_authority') or 'unknown'}"
)

st.divider()
st.subheader("Automation policy")

holiday_text = "\n".join(
    str(value)
    for value in calendar.get("holiday_dates", [])
)
special_text = "\n".join(
    str(value)
    for value in calendar.get(
        "special_trading_dates",
        [],
    )
)

with st.form("market_day_operations_policy"):
    p1, p2, p3 = st.columns(3)
    with p1:
        automation_enabled = st.toggle(
            "Enable scheduled operations",
            value=bool(
                policy.get("automation_enabled", False)
            ),
        )
    with p2:
        market_day_only = st.toggle(
            "Market days only",
            value=bool(
                policy.get("market_day_only", True)
            ),
        )
    with p3:
        context_limit = st.number_input(
            "Market-context sample",
            min_value=25,
            max_value=500,
            step=25,
            value=int(
                policy.get("market_context_limit") or 100
            ),
        )

    st.markdown("**Morning · pre-market control cycle**")
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        morning_enabled = st.toggle(
            "Morning enabled",
            value=bool(morning.get("enabled", True)),
        )
    with a2:
        morning_time = st.text_input(
            "Morning time IST",
            value=str(morning.get("time_ist") or "08:45"),
            max_chars=5,
        )
    with a3:
        morning_grace = st.number_input(
            "Morning grace (min)",
            min_value=5,
            max_value=180,
            value=int(morning.get("grace_minutes") or 30),
        )
    with a4:
        morning_refresh = st.toggle(
            "Refresh market context",
            value=bool(
                morning.get(
                    "refresh_market_context",
                    True,
                )
            ),
        )
    morning_notify = st.toggle(
        "Morning Discord operational summary",
        value=bool(morning.get("notify_discord", True)),
    )

    st.markdown("**End of day · paper safety & close snapshot**")
    e1, e2, e3, e4 = st.columns(4)
    with e1:
        eod_enabled = st.toggle(
            "EOD enabled",
            value=bool(eod.get("enabled", True)),
        )
    with e2:
        eod_time = st.text_input(
            "EOD time IST",
            value=str(eod.get("time_ist") or "15:45"),
            max_chars=5,
        )
    with e3:
        eod_grace = st.number_input(
            "EOD grace (min)",
            min_value=5,
            max_value=180,
            value=int(eod.get("grace_minutes") or 30),
        )
    with e4:
        eod_refresh = st.toggle(
            "Refresh close context",
            value=bool(
                eod.get(
                    "refresh_market_context",
                    True,
                )
            ),
        )

    e5, e6, e7 = st.columns(3)
    with e5:
        paper_safety_tick = st.toggle(
            "Paper force-exit safety tick",
            value=bool(
                eod.get("paper_safety_tick", True)
            ),
        )
    with e6:
        portfolio_sync = st.toggle(
            "Read-only Kite portfolio sync",
            value=bool(
                eod.get("portfolio_sync", False)
            ),
        )
    with e7:
        eod_notify = st.toggle(
            "EOD Discord operational summary",
            value=bool(eod.get("notify_discord", True)),
        )

    c1, c2 = st.columns(2)
    with c1:
        holidays = st.text_area(
            "NSE holiday overrides",
            value=holiday_text,
            height=110,
            help="One YYYY-MM-DD date per line.",
        )
    with c2:
        special_days = st.text_area(
            "Special trading-day overrides",
            value=special_text,
            height=110,
            help=(
                "One YYYY-MM-DD date per line. "
                "Use for an explicitly known weekend trading session."
            ),
        )

    save_policy = st.form_submit_button(
        "Save operations policy",
        type="primary",
        use_container_width=True,
    )


def date_lines(value: str) -> list[str]:
    rows = []
    for raw in value.replace(",", "\n").splitlines():
        item = raw.strip()
        if item and item not in rows:
            rows.append(item)
    return rows


if save_policy:
    if not admin_key_configured():
        st.error(
            "Configure the production admin key before changing operations policy."
        )
    else:
        payload = {
            "automation_enabled": automation_enabled,
            "market_day_only": market_day_only,
            "calendar": {
                "holiday_dates": date_lines(holidays),
                "special_trading_dates": date_lines(
                    special_days
                ),
            },
            "market_context_limit": int(context_limit),
            "morning": {
                "enabled": morning_enabled,
                "time_ist": morning_time.strip(),
                "grace_minutes": int(morning_grace),
                "refresh_market_context": morning_refresh,
                "notify_discord": morning_notify,
            },
            "eod": {
                "enabled": eod_enabled,
                "time_ist": eod_time.strip(),
                "grace_minutes": int(eod_grace),
                "paper_safety_tick": paper_safety_tick,
                "refresh_market_context": eod_refresh,
                "portfolio_sync": portfolio_sync,
                "notify_discord": eod_notify,
            },
        }
        try:
            client.put_json(
                "/operations/policy",
                payload,
                timeout=30,
            )
            st.success("Operations policy updated.")
            st.rerun()
        except ApiError as exc:
            render_api_error(
                exc,
                title="Operations policy update failed",
            )

st.divider()
st.subheader("Manual control")

force = st.toggle(
    "Force manual run",
    value=False,
    help=(
        "Force bypasses the market-day, operation-enabled and "
        "same-day completion guards. It does not enable broker orders."
    ),
)

b1, b2, b3, b4 = st.columns(4)
with b1:
    run_morning = st.button(
        "Run morning now",
        use_container_width=True,
    )
with b2:
    run_eod = st.button(
        "Run EOD now",
        use_container_width=True,
    )
with b3:
    run_tick = st.button(
        "Tick scheduler",
        use_container_width=True,
    )
with b4:
    reset_policy = st.button(
        "Reset policy",
        use_container_width=True,
    )


def require_admin() -> bool:
    if admin_key_configured():
        return True
    st.error(
        "Configure the production admin key for operations mutations."
    )
    return False


if run_morning and require_admin():
    try:
        with st.spinner("Running morning operations..."):
            result = client.post_json(
                "/operations/run/morning",
                {"force": bool(force)},
                timeout=920,
            )
        st.success(
            f"Morning operation status: {result.get('status')}"
        )
        st.json(result)
    except ApiError as exc:
        render_api_error(
            exc,
            title="Morning operation failed",
        )

if run_eod and require_admin():
    try:
        with st.spinner("Running EOD operations..."):
            result = client.post_json(
                "/operations/run/eod",
                {"force": bool(force)},
                timeout=920,
            )
        st.success(
            f"EOD operation status: {result.get('status')}"
        )
        st.json(result)
    except ApiError as exc:
        render_api_error(
            exc,
            title="EOD operation failed",
        )

if run_tick and require_admin():
    try:
        with st.spinner("Evaluating scheduled operation windows..."):
            result = client.post_json(
                "/operations/tick",
                {},
                timeout=920,
            )
        st.info(
            f"Scheduler tick: {result.get('status')}"
        )
        st.json(result)
    except ApiError as exc:
        render_api_error(
            exc,
            title="Scheduler tick failed",
        )

if reset_policy and require_admin():
    try:
        client.delete_json(
            "/operations/policy",
            timeout=30,
        )
        st.success(
            "Operations policy reset to safe built-in defaults."
        )
        st.rerun()
    except ApiError as exc:
        render_api_error(
            exc,
            title="Operations policy reset failed",
        )

st.divider()
st.subheader("Current control center")

market = control.get("market")
market = market if isinstance(market, dict) else {}
breadth = market.get("breadth")
breadth = breadth if isinstance(breadth, dict) else {}
regime = market.get("regime")
regime = regime if isinstance(regime, dict) else {}
paper = control.get("paper_monitor")
paper = paper if isinstance(paper, dict) else {}
portfolio = control.get("portfolio")
portfolio = portfolio if isinstance(portfolio, dict) else {}
pnl = control.get("daily_pnl")
pnl = pnl if isinstance(pnl, dict) else {}

q1, q2, q3, q4, q5, q6 = st.columns(6)
with q1:
    st.metric(
        "Regime",
        str(regime.get("regime") or "—").upper(),
    )
with q2:
    st.metric(
        "Breadth",
        str(breadth.get("direction") or "—").upper(),
    )
with q3:
    st.metric(
        "Paper monitor",
        str(paper.get("status") or "—").upper(),
    )
with q4:
    st.metric(
        "Paper positions",
        int(paper.get("open_position_count") or 0),
    )
with q5:
    st.metric(
        "Portfolio value",
        (
            f"₹{float(portfolio.get('portfolio_value') or 0):,.0f}"
            if portfolio.get("portfolio_value") is not None
            else "—"
        ),
    )
with q6:
    st.metric(
        "Daily realized P&L",
        f"₹{float(pnl.get('net_pnl') or 0):,.2f}",
    )

with st.expander("Operational evidence"):
    st.json(control)

st.subheader("Recent operation runs")
runs = history.get("runs")
runs = runs if isinstance(runs, list) else []
if runs:
    rows = []
    for item in runs:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "Date": item.get("date_ist"),
                "Operation": item.get("operation"),
                "Status": item.get("status"),
                "Scheduled": item.get("scheduled"),
                "Forced": item.get("forced"),
                "Completed steps": item.get(
                    "completed_steps"
                ),
                "Failed steps": item.get("failed_steps"),
                "Started": item.get("started_at_ist"),
                "Run ID": item.get("run_id"),
            }
        )
    frame = pd.DataFrame(rows)
    st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Download operations history CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name="trendforge_operations_history.csv",
        mime="text/csv",
    )
else:
    st.info("No scheduled-operation runs have been recorded yet.")

with st.expander("Safety & scheduling semantics"):
    st.markdown(
        """
- Automation is **off by default**.
- Normal scheduled runs honor configured market-day overrides and run only within their configured grace windows.
- A backend restart after a completed job does not repeat that job because completion evidence is persisted.
- Failed/degraded steps remain visible in run evidence; notification delivery cannot change the operational result.
- Morning/EOD operations do **not** launch scanner runs and never place broker orders.
- The EOD paper safety tick uses the existing paper-only quote monitor and 15:00 IST force-exit semantics.
- Optional Kite portfolio sync reads holdings/positions and updates the local reporting snapshot only.
- The in-process worker cannot run while a hosting service is asleep. The admin-protected /operations/tick endpoint can be invoked by an external scheduler if guaranteed timing is required.
"""
    )
