from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "scanner" / "scanner_engine.py").read_text(encoding="utf-8")


def test_scanner_engine_is_explicitly_a_full_pipeline_facade():
    assert "FullScannerPipeline" in SOURCE
    assert "all actual execution is delegated to FullScannerPipeline" in SOURCE
    assert ".analyze(symbol" in SOURCE


def test_scanner_engine_does_not_reimplement_scanner_execution_stages():
    forbidden = (
        "IndicatorEngine(",
        "EngineOrchestrator(",
        ".calculate(",
        ".assert_valid(",
        "MarketDataContract",
        "EngineInputContract",
    )
    offenders = [marker for marker in forbidden if marker in SOURCE]
    assert not offenders, f"ScannerEngine duplicated canonical execution logic: {offenders}"


def test_dataframe_compatibility_path_still_uses_full_pipeline():
    assert "class Adapter:" in SOURCE
    assert "FullScannerPipeline(Adapter(df)" in SOURCE
    assert "canonical.analyze" in SOURCE
