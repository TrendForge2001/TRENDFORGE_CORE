from __future__ import annotations

import pandas as pd

from engines.base_engine import BaseEngine, EngineResult
from engines.engine_orchestrator import EngineOrchestrator
from scanner.full_pipeline import FullScannerPipeline


class FakeProvider:
    def candles(self, symbol, period="6mo", interval="1d"):
        return pd.DataFrame({
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000, 1200],
        })


class FakeIndicators:
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


class ReadyContract:
    def validate(self, stock):
        class Report:
            ready = True
            missing = []
            invalid = []
            def as_dict(self):
                return {"ready": True, "missing": [], "invalid": []}
        return Report()


class PassingEngine(BaseEngine):
    NAME = "Technical Engine"
    mandatory = True
    def evaluate(self, stock):
        return EngineResult(self.NAME, True, 90.0, 100.0, 90.0, "A")


class HardRiskEngine(BaseEngine):
    NAME = "Risk Engine"
    mandatory = True
    def evaluate(self, stock):
        return EngineResult(self.NAME, True, 80.0, 100.0, 80.0, "A", metrics={"hard_block": True})


class FixedSignal:
    def __init__(self, signal):
        self.signal = signal

    def generate_from_results(self, symbol, results):
        class ResultSignal:
            warnings = []
        result = ResultSignal()
        result.signal = self.signal
        return result


def pipeline(signal="BUY", risk=False):
    engines = [PassingEngine()]
    if risk:
        engines.append(HardRiskEngine())
    orchestrator = EngineOrchestrator(engines=engines, input_contract=ReadyContract())
    orchestrator.signal_engine = FixedSignal(signal)
    return FullScannerPipeline(FakeProvider(), orchestrator=orchestrator, indicator_engine=FakeIndicators())


def test_pipeline_preserves_successful_eligibility():
    result = pipeline().analyze("ABC")
    assert result["passed"] is True
    assert result["eligible"] is True
    assert result["signal"].signal == "BUY"


def test_pipeline_propagates_hard_risk_rejection():
    result = pipeline(risk=True).analyze("ABC")
    assert result["passed"] is False
    assert result["eligible"] is False
    assert result["signal"].signal == "HOLD"


def test_pipeline_rejects_negative_signal_even_when_orchestrator_passes():
    result = pipeline(signal="SELL").analyze("ABC")
    assert result["passed"] is True
    assert result["eligible"] is False


def test_analyze_many_keeps_rejected_results_out_of_top_picks():
    scanner = pipeline()
    output = scanner.analyze_many(["ABC", "XYZ"], top_n=20)
    assert output["count"] == 2
    assert len(output["top_picks"]) == 2
    assert all(item["eligible"] for item in output["top_picks"])
