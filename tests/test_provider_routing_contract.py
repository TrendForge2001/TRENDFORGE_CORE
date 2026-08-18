from __future__ import annotations

import pandas as pd
import pytest

from providers.routed_market_data_provider import RoutedMarketDataProvider


class GoodProvider:
    def __init__(self, name="good"):
        self.name = name
        self.calls = 0

    def candles(self, symbol, period="1y", interval="1d"):
        self.calls += 1
        return pd.DataFrame({"open": [1], "high": [2], "low": [0], "close": [1.5], "volume": [100]})


class FailingProvider:
    def __init__(self):
        self.calls = 0

    def candles(self, symbol, period="1y", interval="1d"):
        self.calls += 1
        raise RuntimeError("primary unavailable")


class EmptyProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        return pd.DataFrame()


def test_router_uses_first_successful_provider():
    first = GoodProvider()
    second = GoodProvider()
    router = RoutedMarketDataProvider([first, second])

    result = router.candles("ABC")

    assert not result.empty
    assert first.calls == 1
    assert second.calls == 0
    assert router.last_provider["ABC"] == "GoodProvider"
    assert router.last_errors["ABC"] == []


def test_router_falls_back_after_provider_exception():
    primary = FailingProvider()
    fallback = GoodProvider()
    router = RoutedMarketDataProvider([primary, fallback], fallback_on_error=True)

    result = router.candles("ABC")

    assert not result.empty
    assert primary.calls == 1
    assert fallback.calls == 1
    assert router.last_provider["ABC"] == "GoodProvider"
    assert len(router.last_errors["ABC"]) == 1


def test_router_can_disable_fallback():
    primary = FailingProvider()
    fallback = GoodProvider()
    router = RoutedMarketDataProvider([primary, fallback], fallback_on_error=False)

    with pytest.raises(RuntimeError, match="All market-data providers failed"):
        router.candles("ABC")

    assert primary.calls == 1
    assert fallback.calls == 0
    assert len(router.last_errors["ABC"]) == 1


def test_empty_provider_output_is_treated_as_failure():
    fallback = GoodProvider()
    router = RoutedMarketDataProvider([EmptyProvider(), fallback])

    result = router.candles("ABC")

    assert not result.empty
    assert router.last_provider["ABC"] == "GoodProvider"
    assert len(router.last_errors["ABC"]) == 1


def test_router_requires_at_least_one_provider():
    with pytest.raises(ValueError, match="At least one market-data provider"):
        RoutedMarketDataProvider([])


def test_router_health_exposes_order_and_fallback_policy():
    router = RoutedMarketDataProvider([GoodProvider(), FailingProvider()], fallback_on_error=False)
    health = router.health()

    assert health["status"] == "configured"
    assert health["fallback_on_error"] is False
    assert health["providers"] == ["GoodProvider", "FailingProvider"]
