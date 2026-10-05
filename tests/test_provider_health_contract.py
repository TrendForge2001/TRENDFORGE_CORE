"""Provider health contract regression coverage."""

from __future__ import annotations

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
