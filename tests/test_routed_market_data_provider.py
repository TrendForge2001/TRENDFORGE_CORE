from __future__ import annotations

import pandas as pd

from providers.routed_market_data_provider import RoutedMarketDataProvider


class FailingProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        raise RuntimeError("unavailable")


class WorkingProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        return pd.DataFrame({
            "open": [100], "high": [102], "low": [99],
            "close": [101], "volume": [1000],
        })


def test_router_falls_back_in_order():
    router = RoutedMarketDataProvider([FailingProvider(), WorkingProvider()])
    frame = router.candles("ABC")
    assert float(frame.iloc[-1]["close"]) == 101
    assert router.last_provider["ABC"] == "WorkingProvider"
    assert len(router.last_errors["ABC"]) == 1


def test_router_can_disable_fallback():
    router = RoutedMarketDataProvider([FailingProvider(), WorkingProvider()], fallback_on_error=False)
    try:
        router.candles("ABC")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected provider failure")
