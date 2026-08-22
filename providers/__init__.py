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
]
