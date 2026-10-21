"""Focused TrendForge navigation for the trading workspace."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageSpec:
    path: str
    title: str
    purpose: str


DEFAULT_PAGE = "pages/watchlists.py"

NAVIGATION_SPEC: dict[str, tuple[PageSpec, ...]] = {
    "Watchlist": (
        PageSpec(
            "pages/watchlists.py",
            "NIFTY 100 Watchlist",
            "Live NIFTY 100 prices and integrated stock detail.",
        ),
    ),
    "Portfolio": (
        PageSpec(
            "pages/portfolio.py",
            "Broker Portfolio",
            "Persisted Kite holdings and positions.",
        ),
        PageSpec(
            "pages/paper_portfolio.py",
            "Paper Trading Portfolio",
            "Separate simulated positions, P&L and closed trades.",
        ),
    ),
    "Fundamentals": (
        PageSpec(
            "pages/fundamentals.py",
            "Fundamentals",
            "Fundamental coverage and research inputs.",
        ),
    ),
    "Technicals": (
        PageSpec(
            "pages/technicals.py",
            "Technical Scanner & Backtesting",
            "NIFTY 500 intraday/swing scanner, paper automation and validation.",
        ),
    ),
    "Scanner Results": (
        PageSpec(
            "pages/scanner_results.py",
            "Scanner Results",
            "Dedicated read-only results for multi-strategy and scheduled technical scans.",
        ),
    ),
    "Corporate Actions": (
        PageSpec(
            "pages/corporate_actions.py",
            "Corporate Actions",
            "Dividends, splits, bonuses and related evidence.",
        ),
    ),
}


def all_pages() -> tuple[PageSpec, ...]:
    return tuple(page for group in NAVIGATION_SPEC.values() for page in group)
