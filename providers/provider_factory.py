"""Canonical construction boundary for TrendForge market-data providers."""
from __future__ import annotations

from typing import Any

from .market_data_adapter import MarketDataAdapter
from .routed_market_data_provider import RoutedMarketDataProvider
from .yfinance_provider import YFinanceProvider


class ProviderFactory:
    """Build scanner-facing market-data adapters without exposing raw providers."""

    def __init__(self, kite=None, yahoo=None, nse=None, fallback_on_error: bool = True, max_workers: int = 8):
        self.kite = kite
        self.yahoo = yahoo or YFinanceProvider()
        self.nse = nse
        self.fallback_on_error = bool(fallback_on_error)
        self.max_workers = max(1, int(max_workers))

    def market_data_provider(self):
        providers: list[Any] = []
        if self.kite is not None:
            providers.append(self.kite)
        if self.yahoo is not None:
            providers.append(self.yahoo)
        return RoutedMarketDataProvider(providers, fallback_on_error=self.fallback_on_error)

    def market_data(self) -> MarketDataAdapter:
        return MarketDataAdapter(self.market_data_provider(), max_workers=self.max_workers)

    def quote(self):
        """Return the explicitly configured quote provider for non-scanner use."""
        if self.kite is not None:
            return self.kite
        if self.nse is not None:
            return self.nse
        return self.yahoo

    def health(self) -> dict[str, Any]:
        adapter = self.market_data()
        return adapter.health()


__all__ = ["ProviderFactory"]
