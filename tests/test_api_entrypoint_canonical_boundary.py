from __future__ import annotations

import inspect

from api.scanner_service import ScannerService
from scanner.full_pipeline import FullScannerPipeline


def test_scanner_service_is_thin_canonical_facade():
    source = inspect.getsource(ScannerService)
    assert "FullScannerPipeline" in source
    assert "EngineOrchestrator" not in source
    assert "IndicatorEngine" not in source
    assert "candles(" not in source


def test_full_pipeline_owns_canonical_execution():
    source = inspect.getsource(FullScannerPipeline)
    assert "EngineOrchestrator" in source
    assert "IndicatorEngine" in source
    assert "self.orchestrator.evaluate" in source


def test_scanner_service_does_not_create_secondary_execution_path():
    source = inspect.getsource(ScannerService)
    forbidden = ("ScannerEngine(", "EngineOrchestrator(", "IndicatorEngine(", "ScoreEngine(")
    assert not any(token in source for token in forbidden)
