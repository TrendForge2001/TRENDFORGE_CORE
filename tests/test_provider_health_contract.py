"""Provider health contract regression coverage."""

from __future__ import annotations

import pandas as pd
import pytest

from providers.market_data_adapter import MarketDataAdapter
from providers.routed_market_data_provider import RoutedMarketDataProvider


class _ConfiguredProvider:
    def health(self):
        return {"status": "configured"}


class _HealthyProvider:
    def health(self):
        return {"status": "healthy"}


class _DegradedProvider:
    def health(self):
        return {"status": "degraded"}


class _NoHealthProvider:
    pass


def test_router_does_not_promote_configured_provider_to_healthy():
    result = RoutedMarketDataProvider([_ConfiguredProvider()]).health()
    assert result["status"] == "configured"


def test_router_requires_all_children_to_be_runtime_healthy():
    result = RoutedMarketDataProvider(
        [_HealthyProvider(), _ConfiguredProvider()]
    ).health()
    assert result["status"] == "configured"


def test_router_degrades_when_any_child_is_degraded():
    result = RoutedMarketDataProvider(
        [_HealthyProvider(), _DegradedProvider()]
    ).health()
    assert result["status"] == "degraded"


def test_router_treats_missing_health_as_configured():
    result = RoutedMarketDataProvider([_NoHealthProvider()]).health()
    assert result["status"] == "configured"
    assert result["provider_health"]["_NoHealthProvider"]["status"] == "configured"


def test_adapter_preserves_configured_provider_state():
    result = MarketDataAdapter(_ConfiguredProvider()).health()
    assert result["status"] == "configured"
    assert result["provider_health"]["status"] == "configured"


def test_adapter_preserves_degraded_provider_state():
    result = MarketDataAdapter(_DegradedProvider()).health()
    assert result["status"] == "degraded"


def test_adapter_promotes_only_explicit_runtime_healthy_state():
    result = MarketDataAdapter(_HealthyProvider()).health()
    assert result["status"] == "healthy"


class _ConfiguredWorkingProvider(_ConfiguredProvider):
    def candles(self, symbol, period="1y", interval="1d"):
        return pd.DataFrame(
            {
                "open": [100.0],
                "high": [102.0],
                "low": [99.0],
                "close": [101.0],
                "volume": [1000.0],
            }
        )


class _ConfiguredFailingProvider(_ConfiguredProvider):
    def candles(self, symbol, period="1y", interval="1d"):
        raise RuntimeError("market runtime unavailable")


def test_adapter_becomes_healthy_after_successful_runtime_candle_fetch():
    adapter = MarketDataAdapter(_ConfiguredWorkingProvider())

    assert adapter.health()["status"] == "configured"

    adapter.candles("ABC")

    health = adapter.health()
    assert health["status"] == "healthy"
    assert health["runtime_status"] == "runtime_verified"
    assert health["last_success_at_epoch"] is not None
    assert health["last_symbol"] == "ABC"
    assert health["last_error"] is None


def test_adapter_degrades_after_runtime_candle_failure():
    adapter = MarketDataAdapter(_ConfiguredFailingProvider())

    with pytest.raises(RuntimeError, match="market runtime unavailable"):
        adapter.candles("ABC")

    health = adapter.health()
    assert health["status"] == "degraded"
    assert health["runtime_status"] == "failed"
    assert health["last_failure_at_epoch"] is not None
    assert health["last_symbol"] == "ABC"
    assert health["last_error"] == "market runtime unavailable"
