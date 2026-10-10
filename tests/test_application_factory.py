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


class DegradedScannerService:
    def health(self):
        return {
            "status": "degraded",
            "pipeline": "FullScannerPipeline",
            "orchestrator": {"status": "unavailable"},
        }


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


def test_application_factory_health_exposes_all_layers(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "missing.db"))
    health = ApplicationFactory(kite=FakeProvider(), yahoo=FakeProvider()).health()

    assert health["status"] == "degraded"
    assert "database" in health
    assert "market_data" in health
    assert "scanner" in health
    assert "domain_providers" in health


def test_application_health_propagates_degraded_scanner_status():
    factory = ApplicationFactory(kite=FakeProvider(), yahoo=FakeProvider())
    factory._scanner_service = DegradedScannerService()

    health = factory.health()

    assert health["scanner"]["status"] == "degraded"
    assert health["status"] == "degraded"


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
    assert health["status"] == "degraded"



def test_application_health_reads_database_health_once(monkeypatch):
    import core.application_factory as application_factory_module

    calls = []

    def fake_database_health():
        calls.append(True)
        return {"status": "not_initialized", "exists": False}

    monkeypatch.setattr(application_factory_module, "database_health", fake_database_health)
    ApplicationFactory(kite=FakeProvider(), yahoo=FakeProvider()).health()

    assert len(calls) == 1


class StubNifty500Provider:
    def __init__(self):
        self.calls = 0

    def nifty500(self, force_refresh=False):
        self.calls += 1
        return {
            "source": "NSE_NIFTY500_CSV",
            "source_url": "https://example.invalid/nifty500.csv",
            "fetched_at": "2026-10-10T00:00:00+00:00",
            "invalid_rows": 0,
            "duplicate_symbols": [],
            "members": [
                {
                    "symbol": f"SYM{i}",
                    "name": f"Company {i}",
                    "sector": "Industrials",
                }
                for i in range(500)
            ],
        }

    def health(self):
        return {
            "status": (
                "runtime_verified"
                if self.calls
                else "configured"
            ),
            "provider": "StubNifty500Provider",
        }


def test_application_factory_owns_single_nifty500_universe():
    provider = StubNifty500Provider()
    factory = ApplicationFactory(
        kite=FakeProvider(),
        yahoo=FakeProvider(),
        nifty500_provider=provider,
    )

    universe = factory.nifty500_universe()
    assert universe is factory.nifty500_universe()

    members = universe.ensure_loaded()
    assert len(members) == 500
    assert provider.calls == 1
    assert universe.health()["status"] == "healthy"


def test_application_health_exposes_universe_without_network_refresh():
    provider = StubNifty500Provider()
    factory = ApplicationFactory(
        kite=FakeProvider(),
        yahoo=FakeProvider(),
        nifty500_provider=provider,
    )

    health = factory.health()

    assert provider.calls == 0
    assert health["universe"]["nifty500"]["status"] == "configured"
    assert health["universe"]["provider"]["status"] == "configured"
