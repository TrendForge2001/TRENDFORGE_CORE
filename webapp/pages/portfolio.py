"""Persisted/live broker portfolio dashboard."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Portfolio",
    "View persisted Kite holdings and trading positions as separate books, with investment, current value, allocation and mark-to-market P&L.",
    kicker="Portfolio",
)

client = api_client(timeout=60)

top_left, top_right = st.columns([3, 1])
with top_left:
    info_note(
        "Portfolio data is persisted from the last successful Kite synchronization. "
        "Use Refresh from Kite to replace the snapshot with the current broker books."
    )
with top_right:
    refresh = st.button(
        "Refresh from Kite",
        type="primary",
        use_container_width=True,
    )

if refresh:
    if not admin_key_configured():
        st.error(
            "The production admin key is required to synchronize the live portfolio."
        )
    else:
        try:
            with st.spinner("Synchronizing Kite portfolio..."):
                sync = client.post_json(
                    "/portfolio/sync",
                    {},
                    timeout=60,
                )
            st.success(
                f"Portfolio synchronized: {sync.get('count', 0)} rows."
            )
        except ApiError as exc:
            render_api_error(
                exc,
                title="Portfolio synchronization failed",
            )

try:
    portfolio = client.get_json("/portfolio")
except ApiError as exc:
    render_api_error(
        exc,
        title="Portfolio snapshot unavailable",
    )
    st.stop()

m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.metric(
        "Investment",
        f"₹{float(portfolio.get('investment') or 0):,.2f}",
    )
with m2:
    st.metric(
        "Current value",
        f"₹{float(portfolio.get('portfolio_value') or 0):,.2f}",
    )
with m3:
    st.metric(
        "Total P&L",
        f"₹{float(portfolio.get('total_pnl') or 0):,.2f}",
    )
with m4:
    st.metric(
        "P&L %",
        f"{float(portfolio.get('total_pnl_pct') or 0):.2f}%",
    )
with m5:
    st.metric(
        "Securities",
        int(portfolio.get("count") or 0),
    )

latest = portfolio.get("latest_updated_at")
if latest:
    st.caption(f"Last persisted broker update: {latest}")
elif portfolio.get("status") == "empty":
    st.warning(
        "No persisted live portfolio rows are available yet. "
        "A valid Kite session is required for the first synchronization."
    )

holdings = portfolio.get("holdings")
positions = portfolio.get("positions")
holdings = holdings if isinstance(holdings, list) else []
positions = positions if isinstance(positions, list) else []

tab_holdings, tab_positions, tab_allocation = st.tabs(
    ["Delivery holdings", "Open positions", "Allocation"]
)

with tab_holdings:
    if holdings:
        frame = pd.DataFrame(holdings)
        st.dataframe(
            frame,
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "Download holdings CSV",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name="trendforge_holdings.csv",
            mime="text/csv",
        )
    else:
        st.info("No persisted delivery holdings.")

with tab_positions:
    if positions:
        frame = pd.DataFrame(positions)
        st.dataframe(
            frame,
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "Download positions CSV",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name="trendforge_positions.csv",
            mime="text/csv",
        )
    else:
        st.info("No persisted open broker positions.")

with tab_allocation:
    books = portfolio.get("book_summary")
    sectors = portfolio.get("sector_summary")
    books = books if isinstance(books, list) else []
    sectors = sectors if isinstance(sectors, list) else []

    if books:
        st.markdown("**Book summary**")
        st.dataframe(
            pd.DataFrame(books),
            use_container_width=True,
            hide_index=True,
        )
    if sectors:
        st.markdown("**Delivery sector allocation**")
        sector_frame = pd.DataFrame(sectors)
        st.dataframe(
            sector_frame,
            use_container_width=True,
            hide_index=True,
        )
        if "sector" in sector_frame and "current_value" in sector_frame:
            chart = sector_frame.set_index("sector")[
                ["current_value"]
            ]
            st.bar_chart(chart)
    if not books and not sectors:
        st.info("Allocation data is not available.")
