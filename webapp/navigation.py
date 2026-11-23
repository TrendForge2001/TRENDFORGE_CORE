"""Focused TrendForge navigation for the trading workspace."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageSpec:
    path: str
    title: str
    purpose: str


DEFAULT_PAGE = "pages/technical_scanner.py"

TECHNICAL_PAGES: dict[str, tuple[PageSpec, ...]] = {
    "Technical Scanner": (
        PageSpec(
            "pages/technical_scanner.py",
            "Stock Scanner",
            "Technical signals, institutional activity and stock data coverage.",
        ),
    ),
    "Backtesting": (
        PageSpec(
            "pages/kite_backtesting.py",
            "Backtesting",
            "Historical Kite candle simulations only.",
        ),
    ),
    "Live Paper Trading": (
        PageSpec(
            "pages/paper_session.py",
            "Paper Trading",
            "Simulated portfolio, risk controls, and Excel P&L.",
        ),
    ),
    "Live Kite Session": (
        PageSpec(
            "pages/live_kite.py",
            "Kite Connection",
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
    "FUNDAMENTALS": (
        PageSpec(
            "pages/fundamental_scan.py",
            "Fundamentals",
            "Reserved for the owner's fundamental rules.",
        ),
    ),
    "INSTITUTIONAL DATA": (
        PageSpec(
            "pages/institutional_scanner.py",
            "Institutional Data",
            (
                "Private disclosed activity, daily technical confirmation and "
                "stock ratings."
            ),
        ),
    ),
}


def all_pages() -> tuple[PageSpec, ...]:
    return tuple(page for group in NAVIGATION_SPEC.values() for page in group)
