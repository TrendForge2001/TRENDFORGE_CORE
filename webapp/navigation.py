"""Central navigation registry for the TrendForge Streamlit application."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageSpec:
    """One navigable Streamlit page."""

    path: str
    title: str
    purpose: str


DEFAULT_PAGE = "pages/dashboard.py"

NAVIGATION_SPEC: dict[str, tuple[PageSpec, ...]] = {
    "Home": (
        PageSpec(
            "pages/dashboard.py",
            "Command Center",
            "System health, market context, scanner readiness and safety status.",
        ),
        PageSpec(
            "pages/watchlists.py",
            "Watchlists",
            "Focused symbols, operator lists and fast market monitoring.",
        ),
        PageSpec(
            "pages/market_day_operations.py",
            "Market-Day Operations",
            "Session controls, run readiness and market-day operating state.",
        ),
    ),
    "Trade": (
        PageSpec(
            "pages/scanner.py",
            "NIFTY 500 Scanner",
            "Rank and inspect TrendForge scanner candidates.",
        ),
        PageSpec(
            "pages/technical_lab.py",
            "Technical Lab",
            "Intraday and swing technical scans plus technical backtests.",
        ),
        PageSpec(
            "pages/paper_trading.py",
            "Paper Trading",
            "Paper positions, entry controls, risk gates and exits.",
        ),
    ),
    "Markets": (
        PageSpec(
            "pages/market_breadth.py",
            "Market Breadth",
            "Participation, advance/decline and breadth confirmation.",
        ),
        PageSpec(
            "pages/market_regime.py",
            "Market Regime",
            "Trend/risk regime context used by trading decisions.",
        ),
        PageSpec(
            "pages/sector_strength.py",
            "Sector Strength",
            "Relative sector leadership and confirmation.",
        ),
    ),
    "Research": (
        PageSpec(
            "pages/weekend_research.py",
            "Weekend Research",
            "Completed-candle stock selection and research-only ranking.",
        ),
        PageSpec(
            "pages/backtesting.py",
            "Backtesting",
            "Historical strategy simulation and performance diagnostics.",
        ),
        PageSpec(
            "pages/fundamentals.py",
            "Fundamentals",
            "Fundamental coverage, evidence, completion and scoring inputs.",
        ),
        PageSpec(
            "pages/news_intelligence.py",
            "News Intelligence",
            "Persisted market/news evidence and sentiment context.",
        ),
        PageSpec(
            "pages/big_shark.py",
            "Big Shark Activity",
            "Institutional and large-holder confirmation signals.",
        ),
        PageSpec(
            "pages/corporate_actions.py",
            "Corporate Actions",
            "Dividends, splits, bonuses and related scoring context.",
        ),
    ),
    "Portfolio": (
        PageSpec(
            "pages/portfolio.py",
            "Portfolio",
            "Holdings, exposure and portfolio state.",
        ),
        PageSpec(
            "pages/pnl.py",
            "P&L Statement",
            "Realized/unrealized trading result views.",
        ),
        PageSpec(
            "pages/performance.py",
            "Performance",
            "Trading performance, returns and effectiveness metrics.",
        ),
    ),
    "Operations": (
        PageSpec(
            "pages/scan_history.py",
            "Scan History",
            "Past scanner runs, outcomes and traceability.",
        ),
        PageSpec(
            "pages/notification_center.py",
            "Notification Center",
            "Alert readiness, policy and delivery state.",
        ),
        PageSpec(
            "pages/scheduler_reliability.py",
            "Scheduler Reliability",
            "Scheduled-run coverage, missed runs and reliability controls.",
        ),
        PageSpec(
            "pages/system.py",
            "System & Access",
            "Backend configuration, access state and system diagnostics.",
        ),
    ),
}


def all_pages() -> tuple[PageSpec, ...]:
    """Return every page in deterministic navigation order."""
    return tuple(page for group in NAVIGATION_SPEC.values() for page in group)
