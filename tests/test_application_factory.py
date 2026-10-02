from __future__ import annotations

from api.scanner_service import ScannerService
from core.application_factory import ApplicationFactory
from core.domain_provider_factory import DomainProviderFactory
from providers import CorporateActionProvider, NewsProvider
from providers.market_data_adapter import MarketDataAdapter
from scanner.full_pipeline import FullScannerPipeline


class FakeProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        raise RuntimeError("not used")


class StubNewsProvider(NewsProvider):
    def news(self, symbol: str):
        return []


class StubCorporateActionProvider(CorporateActionProvider):
    def corporate_actions(self):
        return []


def test_application_factory_builds_canonical_stack():
    factory = ApplicationFactory(kite=FakeProvider(), yahoo=FakeProvider())

    adapter = factory.market_data()
    pipeline = factory.scanner_pipeline()
    service = factory.scanner_service()

    assert isinstance(adapter, MarketDataAdapter)
    assert isinstance(pipeline, FullScannerPipeline)
    assert pipeline.provider is not None
    assert isinstance(service, ScannerService)
    assert service.pipeline is pipeline


def test_application_factory_composes_domain_provider_services():
    news = StubNewsProvider()
    corporate_actions = StubCorporateActionProvider()
    factory = ApplicationFactory(
        domain_provider_factory=DomainProviderFactory(
            news_provider=news,
            corporate_action_provider=corporate_actions,
        )
    )

    assert factory.news_provider() is news
    assert factory.corporate_action_provider() is corporate_actions
    assert factory.news_service().provider is news
    assert factory.corporate_action_service().provider is corporate_actions


def test_application_factory_health_exposes_all_layers():
    health = ApplicationFactory(kite=FakeProvider(), yahoo=FakeProvider()).health()

    assert health["status"] == "healthy"
    assert "database" in health
    assert "market_data" in health
    assert "scanner" in health
    assert "domain_providers" in health


def test_application_health_reports_domain_provider_composition():
    factory = ApplicationFactory(
        domain_provider_factory=DomainProviderFactory(
            news_provider=StubNewsProvider(),
            corporate_action_provider=StubCorporateActionProvider(),
        )
    )

    health = factory.health()
    assert health["domain_providers"] == {
        "news": "StubNewsProvider",
        "corporate_actions": "StubCorporateActionProvider",
    }


def test_application_health_reports_database_readiness_without_kite_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "missing.db"))
    factory = ApplicationFactory(kite=FakeProvider(), yahoo=FakeProvider())
    health = factory.health()
    assert health["database"]["status"] == "not_initialized"
    assert health["database"]["exists"] is False
    assert health["configuration"]["kite_configured"] is False
