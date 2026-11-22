"""Focused TrendForge navigation for the trading workspace."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageSpec:
    path: str
    title: str
    purpose: str


DEFAULT_PAGE = "pages/watchlists.py"

TECHNICAL_PAGES: dict[str, tuple[PageSpec, ...]] = {
    "Watchlist": (
        PageSpec(
            "pages/watchlists.py",
            "Stock Watchlists",
            "Shared stock lists, sector groups, Kite prices and daily change.",
        ),
    ),
    "Technical Scanner": (
        PageSpec(
            "pages/technical_scanner.py",
            "Technical Scanner",
            "Indicator-driven Kite technical signals and results.",
        ),
    ),
    "Backtesting": (
        PageSpec(
            "pages/kite_backtesting.py",
            "Kite Backtesting",
            "Historical Kite candle simulations only.",
        ),
    ),
    "Live Paper Trading": (
        PageSpec(
            "pages/paper_session.py",
            "Live Paper Trading",
            "Simulated portfolio, risk controls, and Excel P&L.",
        ),
    ),
    "Live Kite Session": (
        PageSpec(
            "pages/live_kite.py",
            "Live Kite Session",
            "Authenticated broker account and order-session monitoring.",
        ),
    ),
    "Reports": (
        PageSpec(
            "pages/reports.py",
            "Reports",
            "Batch progress, scanner results and completed entry/exit reports.",
        ),
    ),
}

NAVIGATION_SPEC: dict[str, tuple[PageSpec, ...]] = {
    "TECHNICAL SCAN": tuple(
        page for group in TECHNICAL_PAGES.values() for page in group
    ),
    "FUNDAMENTAL SCAN": (
        PageSpec(
            "pages/fundamental_scan.py",
            "Fundamental Scanner",
            "Reserved for the owner's fundamental rules.",
        ),
    ),
    "AMC / BIG SHARK / INSTITUTIONAL": (
        PageSpec(
            "pages/institutional_scanner.py",
            "Institutional Scanner",
            "Private disclosed activity, daily technical confirmation and stock ratings.",
        ),
    ),
}


def all_pages() -> tuple[PageSpec, ...]:
    return tuple(page for group in NAVIGATION_SPEC.values() for page in group)
