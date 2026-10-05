from __future__ import annotations

from pipeline.scan_pipeline import ScanPipeline
from scanner.pipeline import ScannerPipeline


class FakeFullPipeline:
    def __init__(self, result=None):
        self.result = result or {
            "passed": True,
            "score": 88,
            "confidence": 88,
            "signal": "BUY",
            "results": [{"symbol": "ABC", "score": 88}],
            "top_picks": [{"symbol": "ABC", "score": 88}],
            "count": 1,
            "scanned_count": 1,
        }
        self.calls = []

    def analyze(self, symbol, **kwargs):
        self.calls.append(("analyze", symbol, kwargs))
        return {**self.result, "symbol": symbol}

    def analyze_many(self, symbols, **kwargs):
        self.calls.append(("analyze_many", symbols, kwargs))
        return dict(self.result)

    def health(self):
        return {"status": "healthy"}


class FakeProvider:
    def candles(self, symbol, period="6mo", interval="1d"):
        raise AssertionError("legacy wrapper must not fetch market data directly")


def test_scanner_pipeline_delegates_to_canonical_pipeline():
    pipeline = FakeFullPipeline()
    facade = ScannerPipeline(pipeline=pipeline)

    result = facade.scan_symbol("ABC")

    assert result["signal"] == "BUY"
    assert pipeline.calls[0][0] == "analyze"


def test_scanner_pipeline_top_n_only_slices_canonical_output():
    pipeline = FakeFullPipeline()
    facade = ScannerPipeline(pipeline=pipeline)

    result = facade.top_n(["ABC", "XYZ"], n=1)

    assert result["top_picks"] == [{"symbol": "ABC", "score": 88}]
    assert len(pipeline.calls) == 1
    assert pipeline.calls[0][0] == "analyze_many"


def test_scan_pipeline_preserves_canonical_decision_fields():
    pipeline = FakeFullPipeline()
    facade = ScanPipeline(scanner=pipeline)

    result = facade.run(["ABC"], top_n=5)

    assert result["passed"] is True
    assert result["signal"] == "BUY"
    assert result["score"] == 88
    assert result["confidence"] == 88
    assert result["top_picks"] == [{"symbol": "ABC", "score": 88}]
    assert result["ranked"] == result["results"]
    assert result["validated_size"] == 1
    assert result["analyzed_count"] == 1


def test_legacy_pipeline_does_not_create_second_execution_path():
    pipeline = FakeFullPipeline()
    facade = ScanPipeline(scanner=pipeline)
    facade.run(["ABC", "XYZ"])

    assert len(pipeline.calls) == 1
    assert pipeline.calls[0][0] == "analyze_many"
