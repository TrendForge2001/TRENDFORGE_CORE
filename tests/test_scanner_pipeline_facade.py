from __future__ import annotations

from scanner.pipeline import ScannerPipeline


class StubPipeline:
    def analyze(self, symbol, period="6mo", interval="1d"):
        return {"symbol": symbol, "eligible": True}

    def analyze_many(self, symbols, period="6mo", interval="1d"):
        return {"results": [{"symbol": s} for s in symbols], "top_picks": [{"symbol": s} for s in symbols]}


def test_legacy_facade_delegates_single_scan():
    facade = ScannerPipeline(pipeline=StubPipeline())
    assert facade.scan_symbol("abc")["symbol"] == "abc"


def test_legacy_facade_delegates_batch_scan():
    facade = ScannerPipeline(pipeline=StubPipeline())
    result = facade.scan_many(["ABC", "XYZ"])
    assert [item["symbol"] for item in result["results"]] == ["ABC", "XYZ"]


def test_top_n_only_limits_canonical_top_picks():
    facade = ScannerPipeline(pipeline=StubPipeline())
    result = facade.top_n(["A", "B", "C"], n=2)
    assert [item["symbol"] for item in result["top_picks"]] == ["A", "B"]
