from __future__ import annotations

from pipeline import EngineRegistry, ResultAggregator, ScanPipeline
from scanner.full_pipeline import FullScannerPipeline


def test_pipeline_exports_are_compatibility_layers():
    assert EngineRegistry.__module__ == "pipeline.engine_registry"
    assert ResultAggregator.__module__ == "pipeline.result_aggregator"
    assert ScanPipeline.__module__ == "pipeline.scan_pipeline"


def test_scan_pipeline_points_to_canonical_full_pipeline():
    facade = ScanPipeline(scanner=FullScannerPipeline)
    # The class itself is intentionally not accepted as an instance; this test
    # verifies the facade does not silently create a second execution stack.
    assert facade.pipeline is None


def test_result_aggregator_is_non_executing_and_safe_for_empty_results():
    result = ResultAggregator().aggregate({})
    assert result == {"score": 0.0, "confidence": 0.0, "reasons": []}
