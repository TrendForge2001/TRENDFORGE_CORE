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
            "pages/portfolio_workspace.py",
            "Portfolio",
            "Broker holdings and paper portfolio in one tabbed workspace.",
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
            "pages/technical_workspace.py",
            "Technicals",
            "Scanner, backtesting, and saved results in one tabbed workspace.",
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
