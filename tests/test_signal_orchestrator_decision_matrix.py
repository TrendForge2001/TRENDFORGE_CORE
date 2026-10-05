from __future__ import annotations

from dataclasses import dataclass

from engines.base_engine import BaseEngine, EngineResult
from engines.engine_orchestrator import EngineOrchestrator


class ReadyContract:
    def validate(self, stock):
        @dataclass
        class Report:
            ready: bool = True
            missing: list[str] = None
            invalid: list[str] = None
            def as_dict(self):
                return {"ready": self.ready, "missing": self.missing or [], "invalid": self.invalid or []}
        return Report()


class MandatoryEngine(BaseEngine):
    mandatory = True
    def __init__(self, name="Technical Engine", passed=True):
        self.NAME = name
        self._passed = passed
    def evaluate(self, stock):
        return EngineResult(self.NAME, self._passed, 80 if self._passed else 0, 100, 80 if self._passed else 0, "A" if self._passed else "F")


class RiskEngine(BaseEngine):
    NAME = "Risk Engine"
    mandatory = True
    def __init__(self, hard_block=False): self.hard_block = hard_block
    def evaluate(self, stock):
        return EngineResult(self.NAME, True, 80, 100, 80, "A", metrics={"hard_block": self.hard_block})


class FixedSignal:
    def __init__(self, value="BUY"): self.value = value
    def generate_from_results(self, symbol, results):
        @dataclass
        class Signal:
            signal: str
            warnings: list[str]
        return Signal(self.value, [])


def make_orchestrator(signal="BUY", hard_block=False, mandatory_pass=True):
    engines = [
        MandatoryEngine("Market Regime Engine", mandatory_pass),
        MandatoryEngine("Price Action Engine", mandatory_pass),
        MandatoryEngine("Technical Engine", mandatory_pass),
        RiskEngine(hard_block),
    ]
    orchestrator = EngineOrchestrator(engines=engines, input_contract=ReadyContract())
    orchestrator.signal_engine = FixedSignal(signal)
    return orchestrator


def test_normal_buy_passes():
    result = make_orchestrator().evaluate({"symbol": "ABC"})
    assert result["passed"] is True
    assert result["signal"].signal == "BUY"


def test_hard_risk_block_forces_hold_and_failure():
    result = make_orchestrator(hard_block=True).evaluate({"symbol": "ABC"})
    assert result["passed"] is False
    assert result["signal"].signal == "HOLD"


def test_mandatory_engine_failure_forces_hold_and_failure():
    result = make_orchestrator(mandatory_pass=False).evaluate({"symbol": "ABC"})
    assert result["passed"] is False
    assert result["signal"].signal == "HOLD"
    assert result["failed_mandatory"]


def test_non_buy_signal_is_not_changed_by_hard_block_but_still_fails():
    result = make_orchestrator(signal="SELL", hard_block=True).evaluate({"symbol": "ABC"})
    assert result["passed"] is False
    assert result["signal"].signal == "SELL"
    assert any("Hard-risk veto active" in warning for warning in result["signal"].warnings)
