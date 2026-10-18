"""TrendForge Streamlit application entry point."""
from __future__ import annotations

import streamlit as st

from webapp.access import render_access_gate
from webapp.runtime import admin_key_configured, api_url, initialize_runtime
from webapp.ui import apply_theme, render_brand


st.set_page_config(
    page_title="TrendForge",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
initialize_runtime()
apply_theme()

if not render_access_gate():
    st.stop()

with st.sidebar:
    render_brand()
    st.caption("API")
    st.code(api_url(), language=None)
    st.caption(
        "Admin key: configured"
        if admin_key_configured()
        else "Admin key: not configured"
    )
    st.divider()

navigation = st.navigation(
    {
        "Monitor": [
            st.Page(
                "pages/dashboard.py",
                title="Command Center",
                default=True,
            ),
            st.Page(
                "pages/market_day_operations.py",
                title="Market-Day Operations",
            ),
            st.Page(
                "pages/scan_history.py",
                title="Scan History",
            ),
            st.Page(
                "pages/notification_center.py",
                title="Notification Center",
            ),
            st.Page("pages/system.py", title="System"),
        ],
        "Operate": [
            st.Page(
                "pages/scanner.py",
                title="NIFTY 500 Scanner",
            ),
            st.Page(
                "pages/watchlists.py",
                title="Watchlists",
            ),
            st.Page(
                "pages/paper_trading.py",
                title="Paper Trading",
            ),
        ],
        "Market": [
            st.Page(
                "pages/market_breadth.py",
                title="Market Breadth",
            ),
            st.Page(
                "pages/market_regime.py",
                title="Market Regime",
            ),
            st.Page(
                "pages/sector_strength.py",
                title="Sector Strength",
            ),
        ],
        "Intelligence": [
            st.Page(
                "pages/news_intelligence.py",
                title="News Intelligence",
            ),
            st.Page(
                "pages/big_shark.py",
                title="Big Shark Activity",
            ),
            st.Page(
                "pages/corporate_actions.py",
                title="Corporate Actions",
            ),
        ],
        "Research": [
            st.Page(
                "pages/backtesting.py",
                title="Backtesting",
            ),
            st.Page(
                "pages/weekend_research.py",
                title="Weekend Research & Stock Selection",
            ),
        ],
        "Portfolio": [
            st.Page(
                "pages/portfolio.py",
                title="Portfolio",
            ),
            st.Page(
                "pages/pnl.py",
                title="P&L Statement",
            ),
            st.Page(
                "pages/performance.py",
                title="Performance",
            ),
        ],
        "Data": [
            st.Page(
                "pages/fundamentals.py",
                title="Fundamentals",
            ),
        ],
    }
)
navigation.run()
