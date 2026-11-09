"""PC paper workspace: live status plus separate supervised-entry controls."""

import streamlit as st

from webapp.api_client import ApiError
from webapp.paper_workspace import render_live_paper_workspace
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import page_header, render_api_error

page_header(
    "Live Paper Trading",
    "Simulated positions, saved-strategy automation, and strategy P&L statements.",
    kicker="04 / Paper Trading",
)
client = api_client(timeout=30)
if st.button(
    "Activate paper kill switch",
    key="paper_kill_activate",
    disabled=not admin_key_configured(),
    width="stretch",
):
    try:
        client.post_json("/paper/kill-switch", {"enabled": True})
        st.rerun()
    except ApiError as exc:
        render_api_error(exc)
can_enter = render_live_paper_workspace(client)

with st.expander("Supervised paper entry", expanded=False):
    with st.form("tf_r726_paper_entry"):
        symbol = st.text_input("NSE symbol", value="RELIANCE").strip().upper()
        side = st.segmented_control(
            "Paper side", ["BUY", "SHORT"], default="BUY", selection_mode="single"
        )
        qty = st.number_input("Quantity", min_value=1, value=1)
        price = st.number_input(
            "Simulated entry (₹)", min_value=0.01, value=100.0, step=0.05
        )
        stop = st.number_input("Stop loss (₹)", min_value=0.0, value=0.0)
        target = st.number_input("Target (₹)", min_value=0.0, value=0.0)
        submit = st.form_submit_button("Open paper position", disabled=not can_enter)
    if submit:
        if not can_enter:
            st.error("New paper entries are currently disabled.")
        else:
            try:
                client.post_json(
                    "/paper/open",
                    {
                        "symbol": symbol,
                        "side": side,
                        "quantity": int(qty),
                        "price": float(price),
                        "stoploss": float(stop),
                        "target2": float(target),
                    },
                )
                st.success("Simulated paper position submitted.")
                st.rerun()
            except ApiError as exc:
                render_api_error(exc, title="Paper entry rejected")
with st.expander("Paper risk controls", expanded=False):
    st.caption("Kill controls and manual monitoring")
    if not admin_key_configured():
        st.warning("The Admin API Key is required for paper mutations.")
    if st.button(
        "Release paper kill switch",
        key="paper_kill_release",
        disabled=not admin_key_configured(),
        width="stretch",
    ):
        try:
            client.post_json("/paper/kill-switch", {"enabled": False})
            st.rerun()
        except ApiError as exc:
            render_api_error(exc)
    if st.button(
        "Run paper quote/SL monitor",
        disabled=not admin_key_configured(),
        width="stretch",
    ):
        try:
            st.json(client.post_json("/paper/monitor/tick", {}, timeout=90))
            st.rerun()
        except ApiError as exc:
            render_api_error(exc)
    if st.button(
        "Run strategy exit check", disabled=not admin_key_configured(), width="stretch"
    ):
        try:
            st.json(client.post_json("/paper/strategy-monitor/tick", {}, timeout=120))
        except ApiError as exc:
            render_api_error(exc)
