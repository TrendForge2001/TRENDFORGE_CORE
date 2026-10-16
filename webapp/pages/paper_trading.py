"""Paper trading operations page."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Paper Trading",
    "Inspect simulated positions, open supervised paper orders, operate the paper kill switch, and verify the automatic quote monitor.",
    kicker="Execution",
)

info_note(
    "This page controls TrendForge paper trading only. Real broker execution is outside the R67 paper-trading path."
)
if not admin_key_configured():
    info_note("Production paper mutations require the admin key.", danger=True)

client = api_client()


def get_or_none(path: str):
    try:
        return client.get_json(path)
    except ApiError:
        return None


readiness = get_or_none("/paper/readiness")
auto_readiness = get_or_none("/paper/auto-entry/readiness")
snapshot = get_or_none("/paper")

r1, r2, r3, r4 = st.columns(4)
with r1:
    st.metric(
        "Paper runtime",
        str((readiness or {}).get("status", "unavailable")).upper(),
    )
with r2:
    kill_state = (readiness or {}).get("kill_switch")
    if kill_state is None:
        kill_state = (readiness or {}).get("runtime_kill_switch")
    st.metric("Kill switch", "ON" if kill_state else "OFF")
with r3:
    monitor = (readiness or {}).get("automatic_monitor") or {}
    st.metric(
        "Quote monitor",
        str(monitor.get("status", "unknown")).upper()
        if isinstance(monitor, dict)
        else "UNKNOWN",
    )
with r4:
    st.metric(
        "Auto-entry",
        "ON" if (auto_readiness or {}).get("enabled") else "OFF",
    )

st.subheader("Open positions")
positions = []
if isinstance(snapshot, dict):
    for key in ("positions", "open_positions", "trades", "items"):
        value = snapshot.get(key)
        if isinstance(value, list):
            positions = [
                row for row in value if isinstance(row, dict)
            ]
            break
        if isinstance(value, dict):
            positions = [
                {
                    "symbol": symbol,
                    **(
                        payload
                        if isinstance(payload, dict)
                        else {"value": payload}
                    ),
                }
                for symbol, payload in value.items()
            ]
            break

if positions:
    st.dataframe(
        pd.DataFrame(positions),
        use_container_width=True,
        hide_index=True,
    )
elif snapshot is not None:
    st.info("No open paper positions.")
else:
    st.warning("Paper snapshot is unavailable.")

left, right = st.columns([1.15, 1])
with left:
    st.subheader("Open paper order")
    with st.form("paper_order"):
        symbol = (
            st.text_input("Symbol", placeholder="TCS")
            .strip()
            .upper()
        )
        side = st.selectbox("Side", ["BUY", "SELL", "SHORT"])
        quantity = st.number_input(
            "Quantity",
            min_value=1,
            value=1,
            step=1,
        )
        price = st.number_input(
            "Entry price",
            min_value=0.01,
            value=100.0,
            step=0.05,
        )
        stoploss = st.number_input(
            "Stop loss",
            min_value=0.0,
            value=0.0,
            step=0.05,
        )
        target2 = st.number_input(
            "Target",
            min_value=0.0,
            value=0.0,
            step=0.05,
        )
        open_order = st.form_submit_button(
            "Open paper position",
            type="primary",
            use_container_width=True,
        )

    if open_order:
        if not symbol:
            st.error("Symbol is required.")
        else:
            try:
                response = client.post_json(
                    "/paper/open",
                    {
                        "symbol": symbol,
                        "side": side,
                        "quantity": int(quantity),
                        "price": float(price),
                        "stoploss": float(stoploss),
                        "target2": float(target2),
                    },
                )
                st.success("Paper order accepted.")
                st.json(response)
            except ApiError as exc:
                render_api_error(exc, title="Paper order failed")

with right:
    st.subheader("Runtime controls")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Enable kill switch", use_container_width=True):
            try:
                st.json(
                    client.post_json(
                        "/paper/kill-switch",
                        {"enabled": True},
                    )
                )
            except ApiError as exc:
                render_api_error(exc)
    with c2:
        if st.button("Disable kill switch", use_container_width=True):
            try:
                st.json(
                    client.post_json(
                        "/paper/kill-switch",
                        {"enabled": False},
                    )
                )
            except ApiError as exc:
                render_api_error(exc)

    if st.button("Run monitor tick", use_container_width=True):
        try:
            st.json(client.post_json("/paper/monitor/tick", {}))
        except ApiError as exc:
            render_api_error(exc)

    if st.button("Refresh page", use_container_width=True):
        st.rerun()

with st.expander("Raw paper snapshot"):
    if snapshot is not None:
        st.json(snapshot)
    if readiness is not None:
        st.markdown("**Readiness**")
        st.json(readiness)
