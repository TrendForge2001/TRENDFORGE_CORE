from __future__ import annotations

import pandas as pd
import pytest

from scanner.full_pipeline import FullScannerPipeline


class FakeIndicators:
    def calculate(self, frame):
        return frame.assign(RSI=55, ATR=2, ADX=25, RVOL=1.5, VWAP=100)

    def latest(self, frame):
        return {"close": 101, "ATR": 2, "RSI": 55, "ADX": 25, "RVOL": 1.5, "VWAP": 100}


class FakeProvider:
    def candles(self, symbol, period="6mo", interval="1d"):
        return pd.DataFrame({"open": [99], "high": [102], "low": [98], "close": [101], "volume": [1000]})


class FakeOrchestrator:
    def evaluate(self, stock):
        return {
            "passed": True,
            "score": 80,
            "max_score": 100,
            "confidence": 80,
            "signal": "BUY",
            "engines": {},
        }


def make_pipeline(orchestrator=None):
    return FullScannerPipeline(FakeProvider(), orchestrator or FakeOrchestrator(), FakeIndicators())


def test_analyze_routes_provider_indicators_and_orchestrator():
    result = make_pipeline().analyze("ABC")
    assert result["symbol"] == "ABC"
    assert result["signal"] == "BUY"
    assert result["eligible"] is True


def test_invalid_provider_output_fails_closed():
    class BadProvider:
        def candles(self, symbol, period="6mo", interval="1d"):
            return pd.DataFrame()

    pipeline = FullScannerPipeline(BadProvider(), FakeOrchestrator(), FakeIndicators())
    with pytest.raises(ValueError, match="No candle data"):
        pipeline.analyze("ABC")


def test_batch_deduplicates_symbols_and_counts_all_results():
    result = make_pipeline().analyze_many(["ABC", "ABC", "XYZ"], top_n=1)
    assert result["scanned_count"] == 2
    assert result["count"] == 2
    assert len(result["top_picks"]) == 1


def test_hold_is_not_eligible():
    class HoldOrchestrator:
        def evaluate(self, stock):
            return {"passed": True, "score": 90, "confidence": 90, "signal": "HOLD", "engines": {}}

    result = make_pipeline(HoldOrchestrator()).analyze("ABC")
    assert result["eligible"] is False


def test_hard_block_is_not_eligible():
    class BlockedOrchestrator:
        def evaluate(self, stock):
            return {
                "passed": True,
                "score": 95,
                "confidence": 95,
                "signal": "BUY",
                "engines": {"Risk Engine": {"metrics": {"hard_block": True}}},
            }

    result = make_pipeline(BlockedOrchestrator()).analyze("ABC")
    assert result["eligible"] is False


def test_non_dict_orchestrator_result_fails():
    class BadOrchestrator:
        def evaluate(self, stock):
            return None

    with pytest.raises(TypeError, match="must return a dict"):
        make_pipeline(BadOrchestrator()).analyze("ABC")
