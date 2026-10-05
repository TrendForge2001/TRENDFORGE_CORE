from __future__ import annotations


def test_canonical_rebuild_modules_import():
    from api.scanner_service import ScannerService
    from core.application_factory import ApplicationFactory
    from engines.engine_orchestrator import EngineOrchestrator
    from providers.market_data_adapter import MarketDataAdapter
    from providers.provider_factory import ProviderFactory
    from providers.routed_market_data_provider import RoutedMarketDataProvider
    from scanner.full_pipeline import FullScannerPipeline

    assert ScannerService is not None
    assert ApplicationFactory is not None
    assert EngineOrchestrator is not None
    assert MarketDataAdapter is not None
    assert ProviderFactory is not None
    assert RoutedMarketDataProvider is not None
    assert FullScannerPipeline is not None


def test_application_factory_owns_canonical_scanner_construction():
    from core.application_factory import ApplicationFactory
    from providers.market_data_adapter import MarketDataAdapter
    from scanner.full_pipeline import FullScannerPipeline

    factory = ApplicationFactory(provider_factory=None)
    pipeline = factory.scanner_pipeline()

    assert isinstance(pipeline, FullScannerPipeline)
    assert isinstance(pipeline.provider, MarketDataAdapter)
    assert pipeline.orchestrator.__class__.__name__ == "EngineOrchestrator"


def test_rebuild_dependency_direction_is_preserved():
    from api.scanner_service import ScannerService
    from scanner.full_pipeline import FullScannerPipeline
    from providers.market_data_adapter import MarketDataAdapter

    assert ScannerService.__module__ == "api.scanner_service"
    assert FullScannerPipeline.__module__ == "scanner.full_pipeline"
    assert MarketDataAdapter.__module__ == "providers.market_data_adapter"
