from __future__ import annotations

import pandas as pd

from scanner.watchlist_manager import WatchlistManager


class FakeRepository:
    def get_all_watchlists(self):
        return [{"watchlist": "Default", "symbol": "ABC"}]

    def add_stock(self, *args):
        pass

    def remove_stock(self, *args):
        pass

    def delete_watchlist(self, *args):
        pass


class FakeMarketData:
    def __init__(self):
        self.calls = []

    def batch_candles(self, symbols, period="1y", interval="1d"):
        self.calls.append((symbols, period, interval))
        return {
            symbol: pd.DataFrame({
                "open": [100.0], "high": [102.0], "low": [99.0],
                "close": [101.0], "volume": [1000],
            })
            for symbol in symbols
        }


def make_manager(monkeypatch):
    monkeypatch.setattr("scanner.watchlist_manager.WatchlistRepository", FakeRepository)
    market_data = FakeMarketData()
    manager = WatchlistManager(market_data=market_data)
    return manager, market_data


def test_quotes_use_market_data_adapter(monkeypatch):
    manager, market_data = make_manager(monkeypatch)
    result = manager.quotes()

    assert "ABC" in result
    assert market_data.calls == [(["ABC"], "5d", "1d")]


def test_quotes_require_canonical_market_data_adapter(monkeypatch):
    manager, _ = make_manager(monkeypatch)
    manager.market_data = None

    try:
        manager.quotes()
    except RuntimeError as exc:
        assert "MarketDataAdapter" in str(exc)
    else:
        raise AssertionError("Expected MarketDataAdapter requirement")
