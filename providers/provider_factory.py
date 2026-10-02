"""Canonical construction boundary for TrendForge market-data providers."""
from __future__ import annotations

from typing import Any

from .market_data_adapter import MarketDataAdapter
from .routed_market_data_provider import RoutedMarketDataProvider
from core.runtime_config import RuntimeConfig, load_runtime_config


class ProviderFactory:
    """Build scanner-facing market-data adapters without external work at import time."""

    def __init__(self, kite=None, yahoo=None, nse=None,
                 fallback_on_error: bool = True, max_workers: int = 8,
                 runtime_config: RuntimeConfig | None = None):
        self.kite = kite
        self.yahoo = yahoo
        self.nse = nse
        self.fallback_on_error = bool(fallback_on_error)
        self.max_workers = max(1, int(max_workers))
        self.runtime_config = runtime_config or load_runtime_config()

    def _default_yahoo(self):
        if self.yahoo is None:
            from .yfinance_provider import YFinanceProvider
            self.yahoo = YFinanceProvider()
        return self.yahoo

    def _default_nse(self):
        if self.nse is None:
            from .nse_provider import NSEProvider
            self.nse = NSEProvider()
        return self.nse

    def _default_kite(self):
        if self.kite is None:
            from .kite_provider import KiteProvider
            self.kite = KiteProvider()
        return self.kite

    def market_data_provider(self):
        providers: list[Any] = []
        if self.kite is not None:
            providers.append(self.kite)
        providers.append(self._default_yahoo())
        return RoutedMarketDataProvider(
            providers, fallback_on_error=self.fallback_on_error
        )

    def market_data(self) -> MarketDataAdapter:
        return MarketDataAdapter(
            self.market_data_provider(), max_workers=self.max_workers
        )

    def quote(self):
        if self.kite is not None:
            return self.kite
        if self.nse is not None:
            return self.nse
        return self._default_yahoo()

    def health(self) -> dict[str, Any]:
        health = self.market_data().health()
        health["configuration"] = {
            "kite_configured": self.runtime_config.kite_configured,
            "kite_authenticated": self.runtime_config.kite_authenticated,
        }
        return health


__all__ = ["ProviderFactory"]
