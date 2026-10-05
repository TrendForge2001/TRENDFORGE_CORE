from __future__ import annotations

from scanner.full_pipeline import FullScannerPipeline
from pipeline.scan_pipeline import ScanPipeline


class FakeProvider:
    def __init__(self):
        self.calls = []

    def candles(self, symbol, period="6mo", interval="1d"):
        self.calls.append((symbol, period, interval))
        import pandas as pd
        return pd.DataFrame({
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000, 1200],
        })


def test_scan_pipeline_uses_full_scanner_pipeline():
    pipeline = FullScannerPipeline(FakeProvider())
    facade = ScanPipeline(scanner=pipeline)
    assert facade.pipeline is pipeline


def test_scan_pipeline_does_not_expose_independent_engine_execution():
    facade = ScanPipeline(scanner=FullScannerPipeline(FakeProvider()))
    assert not hasattr(facade, "_scan_valid_payloads")
    assert not hasattr(facade, "normalizer")
    assert not hasattr(facade, "enricher")


def test_scan_pipeline_requires_market_data_when_constructed_without_canonical_pipeline():
    facade = ScanPipeline()
    try:
        facade.run(["ABC"])
    except ValueError as exc:
        assert "FullScannerPipeline" in str(exc)
    else:
        raise AssertionError("Expected missing provider failure")
