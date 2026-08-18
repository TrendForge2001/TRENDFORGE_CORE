from __future__ import annotations

from core.application_factory import ApplicationFactory
from api.scanner_service import ScannerService
from providers.market_data_adapter import MarketDataAdapter
from scanner.full_pipeline import FullScannerPipeline


class FakeProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        raise RuntimeError("not used")


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


def test_application_factory_health_exposes_all_layers():
    health = ApplicationFactory(kite=FakeProvider(), yahoo=FakeProvider()).health()

    assert health["status"] == "healthy"
    assert "market_data" in health
    assert "scanner" in health
