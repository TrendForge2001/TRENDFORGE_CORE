"""TrendForge providers and canonical domain contracts."""
from __future__ import annotations

from .market_data_provider import MarketDataProvider
from .market_data_adapter import MarketDataAdapter


class NewsProvider:
    """Domain contract for news retrieval."""

    def news(self, symbol: str):
        raise NotImplementedError


class CorporateActionProvider:
    """Domain contract for corporate-action retrieval."""

    def corporate_actions(self):
        raise NotImplementedError


class CompositeNewsProvider(NewsProvider):
    """Concrete news adapter over existing Yahoo/NSE providers."""

    def __init__(self, yahoo=None, nse=None):
        self.yahoo = yahoo
        self.nse = nse

    def _yahoo(self):
        if self.yahoo is None:
            from .yfinance_provider import yfinance_provider
            self.yahoo = yfinance_provider
        return self.yahoo

    def _nse(self):
        if self.nse is None:
            from .nse_provider import nse_provider
            self.nse = nse_provider
        return self.nse

    def news(self, symbol: str):
        items = []
        try:
            items.extend(self._yahoo().news(symbol) or [])
        except Exception:
            pass
        try:
            for item in self._nse().corporate_actions() or []:
                if symbol.upper() in str(item).upper():
                    items.append(item)
        except Exception:
            pass
        return items


class NSECorporateActionProvider(CorporateActionProvider):
    """Concrete corporate-action adapter over NSE."""

    def __init__(self, provider=None):
        self.provider = provider

    def _provider(self):
        if self.provider is None:
            from .nse_provider import nse_provider
            self.provider = nse_provider
        return self.provider

    def corporate_actions(self):
        return self._provider().corporate_actions() or []


__all__ = [
    "MarketDataProvider", "MarketDataAdapter",
    "NewsProvider", "CorporateActionProvider",
    "CompositeNewsProvider", "NSECorporateActionProvider",
]
