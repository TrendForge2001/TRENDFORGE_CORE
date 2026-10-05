from __future__ import annotations

from core.runtime_config import RuntimeConfig
from providers.market_data_adapter import MarketDataAdapter
from providers.provider_factory import ProviderFactory
from providers.routed_market_data_provider import RoutedMarketDataProvider


class FakeProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        raise RuntimeError("not used")


class FakeYahoo:
    def candles(self, symbol, period="1y", interval="1d"):
        raise RuntimeError("not used")


def test_factory_builds_canonical_market_data_adapter():
    adapter = ProviderFactory(kite=FakeProvider(), yahoo=FakeYahoo()).market_data()

    assert isinstance(adapter, MarketDataAdapter)
    assert isinstance(adapter.provider, RoutedMarketDataProvider)
    assert [p.__class__.__name__ for p in adapter.provider.providers] == ["FakeProvider", "FakeYahoo"]


def test_factory_does_not_return_raw_market_data_provider():
    result = ProviderFactory(kite=FakeProvider(), yahoo=FakeYahoo()).market_data()
    assert isinstance(result, MarketDataAdapter)


def test_factory_health_reports_routing_stack():
    health = ProviderFactory(kite=FakeProvider(), yahoo=FakeYahoo()).health()
    assert health["provider"] == "RoutedMarketDataProvider"
    assert health["provider_health"]["fallback_on_error"] is True


def test_quote_boundary_remains_explicit():
    kite = FakeProvider()
    nse = object()
    assert ProviderFactory(kite=kite, yahoo=FakeYahoo(), nse=nse).quote() is kite
    assert ProviderFactory(yahoo=FakeYahoo(), nse=nse).quote() is nse


def test_factory_health_reports_runtime_configuration_without_network_calls():
    health = ProviderFactory(runtime_config=RuntimeConfig()).health()

    assert health["configuration"] == {
        "kite_configured": False,
        "kite_authenticated": False,
    }


class DegradedProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        raise RuntimeError("provider unavailable")

    def health(self):
        return {"status": "degraded", "reason": "provider unavailable"}


def test_market_data_health_propagates_degraded_provider():
    health = ProviderFactory(kite=DegradedProvider(), yahoo=FakeYahoo()).health()

    assert health["status"] == "degraded"
    assert health["provider_health"]["provider_health"]["DegradedProvider"]["status"] == "degraded"


def test_application_factory_health_propagates_degraded_market_data():
    from core.application_factory import ApplicationFactory

    factory = ApplicationFactory(kite=DegradedProvider(), yahoo=FakeYahoo())
    health = factory.health()

    assert health["market_data"]["status"] == "degraded"
    assert health["status"] == "degraded"
