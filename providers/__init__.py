"""TrendForge providers and canonical domain contracts."""

from .market_data_provider import MarketDataProvider
from .market_data_adapter import MarketDataAdapter
from .kite_provider import KiteProvider, kite_provider
from .nse_provider import NSEProvider, nse_provider
from .yfinance_provider import YahooFinanceProvider, yfinance_provider


class NewsProvider:
    """Domain contract for news retrieval."""

    def news(self, symbol: str):
        raise NotImplementedError


class CorporateActionProvider:
    """Domain contract for corporate-action retrieval."""

    def corporate_actions(self):
        raise NotImplementedError


class CompositeNewsProvider(NewsProvider):
    """Concrete news adapter over existing market/news data providers."""

    def __init__(self, yahoo=None, nse=None):
        self.yahoo = yahoo or yfinance_provider
        self.nse = nse or nse_provider

    def news(self, symbol: str):
        items = []
        try:
            items.extend(self.yahoo.news(symbol) or [])
        except Exception:
            pass
        try:
            for item in self.nse.corporate_actions() or []:
                if symbol.upper() in str(item).upper():
                    items.append(item)
        except Exception:
            pass
        return items


class NSECorporateActionProvider(CorporateActionProvider):
    """Concrete corporate-action adapter over the NSE provider."""

    def __init__(self, provider=None):
        self.provider = provider or nse_provider

    def corporate_actions(self):
        return self.provider.corporate_actions() or []


__all__ = [
    "MarketDataProvider",
    "MarketDataAdapter",
    "KiteProvider",
    "kite_provider",
    "NSEProvider",
    "nse_provider",
    "YahooFinanceProvider",
    "yfinance_provider",
    "NewsProvider",
    "CorporateActionProvider",
    "CompositeNewsProvider",
    "NSECorporateActionProvider",
]
