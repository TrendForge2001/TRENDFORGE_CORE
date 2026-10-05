from __future__ import annotations

import pandas as pd

from providers.market_data_adapter import MarketDataAdapter
from providers.routed_market_data_provider import RoutedMarketDataProvider


class FailingProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        raise RuntimeError("Kite unavailable")


class WorkingProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        return pd.DataFrame({
            "open": [100], "high": [102], "low": [99],
            "close": [101], "volume": [1000],
        })


def test_adapter_normalizes_router_fallback():
    router = RoutedMarketDataProvider([FailingProvider(), WorkingProvider()])
    adapter = MarketDataAdapter(router)

    frame = adapter.candles("abc")

    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert float(frame.iloc[-1]["close"]) == 101.0
    assert router.last_provider["ABC"] == "WorkingProvider"


def test_adapter_batch_preserves_per_symbol_failures():
    class SelectiveProvider:
        def candles(self, symbol, period="1y", interval="1d"):
            if symbol == "BAD":
                raise RuntimeError("unavailable")
            return WorkingProvider().candles(symbol, period, interval)

    adapter = MarketDataAdapter(SelectiveProvider())
    results, failures = adapter.batch_candles_with_errors(["GOOD", "BAD", "GOOD"])

    assert list(results) == ["GOOD"]
    assert "BAD" in failures


def test_adapter_health_exposes_router_health():
    router = RoutedMarketDataProvider([FailingProvider(), WorkingProvider()])
    health = MarketDataAdapter(router).health()

    assert health["provider"] == "RoutedMarketDataProvider"
    assert health["provider_health"]["fallback_on_error"] is True
