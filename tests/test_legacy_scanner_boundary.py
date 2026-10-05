from __future__ import annotations

import inspect

from scanner.pipeline import ScannerPipeline
from scanner.scanner_engine import ScannerEngine
from engines.scanner_engine import ScannerEngine as EngineScannerEngine
from scanner.full_pipeline import FullScannerPipeline


def test_scanner_pipeline_is_only_a_full_pipeline_facade():
    source = inspect.getsource(ScannerPipeline)
    assert "FullScannerPipeline" in source
    assert "EngineOrchestrator(" not in source
    assert "IndicatorEngine(" not in source
    assert "ScannerEngine(" not in source


def test_scanner_engine_requires_full_pipeline_for_execution():
    source = inspect.getsource(ScannerEngine)
    assert "FullScannerPipeline" in source
    assert "_require_pipeline" in source
    assert "EngineOrchestrator(" not in source
    assert "IndicatorEngine(" not in source


def test_engines_scanner_engine_is_an_alias_only():
    assert issubclass(EngineScannerEngine, ScannerEngine)
    assert EngineScannerEngine.__module__ == "engines.scanner_engine"


def test_legacy_entrypoints_converge_on_canonical_pipeline():
    assert ScannerPipeline.__init__.__annotations__ is not None
    assert FullScannerPipeline.__name__ == "FullScannerPipeline"
