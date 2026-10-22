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
        PageSpec("pages/watchlists.py", "NIFTY 50 Watchlist", "NIFTY 50 live Kite price and daily change."),
    ),
    "Technical Scanner": (
        PageSpec("pages/technical_scanner.py", "Technical Scanner", "Indicator-driven Kite technical signals and results."),
    ),
    "Backtesting": (
        PageSpec("pages/kite_backtesting.py", "Kite Backtesting", "Historical Kite candle simulations only."),
    ),
    "Live Paper Trading": (
        PageSpec("pages/paper_session.py", "Live Paper Trading", "Simulated portfolio, risk controls, and Excel P&L."),
    ),
    "Live Kite Session": (
        PageSpec("pages/live_kite.py", "Live Kite Session", "Authenticated broker account and order-session monitoring."),
    ),
}


def all_pages() -> tuple[PageSpec, ...]:
    return tuple(page for group in NAVIGATION_SPEC.values() for page in group)
