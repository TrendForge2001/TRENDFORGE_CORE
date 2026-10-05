from __future__ import annotations

from engines.base_engine import BaseEngine, EngineResult
from engines.engine_orchestrator import EngineOrchestrator


class InputContract:
    def validate(self, stock):
        class Report:
            ready = True
            missing = []
            invalid = []
            def as_dict(self): return {"ready": True, "missing": [], "invalid": [], "warnings": []}
        return Report()


class BuyEngine(BaseEngine):
    NAME = "Technical Engine"
    mandatory = True
    def evaluate(self, stock):
        return EngineResult(self.NAME, True, 100, 100, 100, "A")


class RegimeEngine(BaseEngine):
    NAME = "Market Regime Engine"
    mandatory = True
    def evaluate(self, stock):
        return EngineResult(self.NAME, True, 100, 100, 100, "A")


class PriceEngine(BaseEngine):
    NAME = "Price Action Engine"
    mandatory = True
    def evaluate(self, stock):
        return EngineResult(self.NAME, True, 100, 100, 100, "A")


class RiskEngine(BaseEngine):
    NAME = "Risk Engine"
    mandatory = True
    def evaluate(self, stock):
        return EngineResult(self.NAME, True, 0, 100, 0, "C", metrics={"hard_block": True})


class StaticSignal:
    def generate_from_results(self, symbol, results):
        class Signal:
            signal = "BUY"
            warnings = []
        return Signal()


def test_hard_block_always_fails_even_if_signal_is_not_buy():
    orchestrator = EngineOrchestrator(
        engines=[RegimeEngine(), PriceEngine(), BuyEngine(), RiskEngine()],
        input_contract=InputContract(),
    )
    orchestrator.signal_engine = StaticSignal()
    result = orchestrator.evaluate({"symbol": "ABC"})

    assert result["passed"] is False
    assert result["signal"].signal == "HOLD"
    assert any("Hard-risk veto active" in warning for warning in result["signal"].warnings)


def test_hard_block_veto_is_unconditional():
    orchestrator = EngineOrchestrator(
        engines=[RegimeEngine(), PriceEngine(), BuyEngine(), RiskEngine()],
        input_contract=InputContract(),
    )
    orchestrator.signal_engine = StaticSignal()
    result = orchestrator.evaluate({"symbol": "ABC"})
    assert result["passed"] is False
