from __future__ import annotations

from scanner.full_pipeline import FullScannerPipeline
from scanner.scanner_engine import ScannerEngine


class FakeProvider:
    def candles(self, symbol, period="6mo", interval="1d"):
        import pandas as pd
        return pd.DataFrame({
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000, 1200],
        })


def test_scanner_engine_is_compatibility_only():
    pipeline = FullScannerPipeline(FakeProvider())
    scanner = ScannerEngine(pipeline=pipeline)
    assert scanner.pipeline is pipeline
    assert not hasattr(scanner, "orchestrator")
    assert not hasattr(scanner, "readiness")


def test_scanner_engine_cannot_execute_without_canonical_pipeline():
    scanner = ScannerEngine()
    try:
        scanner.scan("ABC", None)
    except ValueError as exc:
        assert "FullScannerPipeline" in str(exc)
    else:
        raise AssertionError("Expected canonical pipeline requirement")


def test_scanner_engine_ranking_is_stable():
    from scanner.scanner_engine import ScanResult
    results = [
        ScanResult("A", 80, "BUY", confidence=80),
        ScanResult("B", 80, "BUY", confidence=90),
        ScanResult("C", 70, "BUY", confidence=99),
    ]
    ranked = ScannerEngine.rank(results)
    assert [item.symbol for item in ranked] == ["B", "A", "C"]
