"""Default runnable scanner construction for TrendForge MVP."""
from __future__ import annotations

from providers.yfinance_provider import YahooFinanceProvider
from services.scanner_service import ScannerService


def build_default_scanner(max_workers: int = 8) -> ScannerService:
    """Build the MVP scanner using Yahoo Finance as the public fallback feed."""
    return ScannerService(provider=YahooFinanceProvider(), max_workers=max_workers)


__all__ = ["build_default_scanner"]
