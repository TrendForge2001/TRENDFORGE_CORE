from __future__ import annotations

import pandas as pd

from scanner.full_pipeline import FullScannerPipeline


class FakeIndicators:
    def calculate(self, frame):
        return frame

    def latest(self, frame):
        return {"close": 100, "ATR": 2, "RSI": 50, "ADX": 20, "RVOL": 1, "VWAP": 100}


class FakeProvider:
    def candles(self, symbol, period="6mo", interval="1d"):
        return pd.DataFrame({"open": [99], "high": [101], "low": [98], "close": [100], "volume": [1000]})


class FakeOrchestrator:
    def __init__(self, result):
        self.result = result

    def evaluate(self, stock):
        return dict(self.result)


def make_pipeline(result):
    return FullScannerPipeline(FakeProvider(), orchestrator=FakeOrchestrator(result), indicator_engine=FakeIndicators())


def test_failed_orchestrator_result_cannot_become_eligible():
    result = make_pipeline({"passed": False, "score": 90, "confidence": 90, "signal": "BUY", "engines": {}}).analyze("ABC")
    assert result["passed"] is False
    assert result["eligible"] is False


def test_hard_block_cannot_become_eligible():
    result = make_pipeline({
        "passed": True, "score": 90, "confidence": 90, "signal": "BUY",
        "engines": {"Risk Engine": {"metrics": {"hard_block": True}}},
    }).analyze("ABC")
    assert result["eligible"] is False


def test_hold_is_rejected_from_eligible_results():
    result = make_pipeline({"passed": True, "score": 70, "confidence": 70, "signal": "HOLD", "engines": {}}).analyze("ABC")
    assert result["eligible"] is False


def test_positive_signal_remains_eligible():
    result = make_pipeline({"passed": True, "score": 70, "confidence": 70, "signal": "BUY", "engines": {}}).analyze("ABC")
    assert result["eligible"] is True


def test_analyze_many_preserves_rejection_and_top_pick_boundaries():
    pipeline = make_pipeline({"passed": False, "score": 100, "confidence": 100, "signal": "BUY", "engines": {}})
    result = pipeline.analyze_many(["ABC", "XYZ"], top_n=1)
    assert result["count"] == 0
    assert result["rejected_count"] == 2
    assert result["top_picks"] == []
