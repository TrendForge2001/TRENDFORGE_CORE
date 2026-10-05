from __future__ import annotations

import pandas as pd

from engines.base_engine import BaseEngine, EngineResult
from engines.engine_orchestrator import EngineOrchestrator
from scanner.full_pipeline import FullScannerPipeline


class Provider:
    def candles(self, symbol, period="6mo", interval="1d"):
        return pd.DataFrame({
            "open": [100.0, 101.0, 102.0],
            "high": [102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0],
            "close": [101.0, 102.0, 103.0],
            "volume": [1000, 1100, 1200],
        })


class Indicators:
    def calculate(self, frame):
        frame = frame.copy()
        frame["ATR"] = 2.0
        frame["RSI"] = 60.0
        frame["ADX"] = 30.0
        frame["RVOL"] = 1.5
        frame["VWAP"] = frame["close"]
        return frame

    def latest(self, frame):
        return frame.iloc[-1].to_dict()


class Engine(BaseEngine):
    NAME = "Test Engine"
    mandatory = True

    def __init__(self, signal="BUY", hard_block=False):
        self.signal = signal
        self.hard_block = hard_block

    def evaluate(self, stock):
        return EngineResult(
            engine=self.NAME,
            passed=True,
            score=90,
            max_score=100,
            confidence=90,
            grade="A",
            metrics={"hard_block": self.hard_block, "symbol": stock["symbol"]},
        )


def pipeline(engine=None):
    return FullScannerPipeline(
        Provider(),
        orchestrator=EngineOrchestrator(engines=[engine or Engine()]),
        indicator_engine=Indicators(),
    )


def test_analyze_has_single_orchestrator_execution_authority():
    orchestrator = EngineOrchestrator(engines=[Engine()])
    calls = {"count": 0}
    original = orchestrator.evaluate

    def evaluate(stock):
        calls["count"] += 1
        return original(stock)

    orchestrator.evaluate = evaluate
    result = FullScannerPipeline(Provider(), orchestrator, Indicators()).analyze("ABC")

    assert calls["count"] == 1
    assert result["symbol"] == "ABC"


def test_hold_result_is_not_eligible():
    class HoldEngine(Engine):
        def evaluate(self, stock):
            result = super().evaluate(stock)
            return result

    orchestrator = EngineOrchestrator(engines=[HoldEngine()])
    original = orchestrator.evaluate
    orchestrator.evaluate = lambda stock: {**original(stock), "signal": "HOLD"}
    result = FullScannerPipeline(Provider(), orchestrator, Indicators()).analyze("ABC")
    assert result["eligible"] is False


def test_hard_block_is_not_eligible():
    result = pipeline(Engine(hard_block=True)).analyze("ABC")
    assert result["eligible"] is False


def test_analyze_many_contains_provider_errors_as_rejected_results():
    class FailingProvider(Provider):
        def candles(self, symbol, period="6mo", interval="1d"):
            if symbol == "BAD":
                raise RuntimeError("provider down")
            return super().candles(symbol, period, interval)

    scanner = FullScannerPipeline(
        FailingProvider(),
        orchestrator=EngineOrchestrator(engines=[Engine()]),
        indicator_engine=Indicators(),
    )
    result = scanner.analyze_many(["GOOD", "BAD"], top_n=5)
    assert result["scanned_count"] == 2
    assert any(item["symbol"] == "BAD" and item["signal"] == "ERROR" for item in result["rejected"])


def test_top_n_is_deterministic_and_bounded():
    result = pipeline().analyze_many(["A", "B", "C"], top_n=2)
    assert len(result["top_picks"]) <= 2
    assert result["top_picks"] == result["eligible"][:2]
