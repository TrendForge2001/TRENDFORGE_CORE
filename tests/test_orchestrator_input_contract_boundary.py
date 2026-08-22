from __future__ import annotations

from engines.engine_orchestrator import EngineOrchestrator
from engines.input_contract import EngineInputContract


class SpyContract(EngineInputContract):
    def __init__(self):
        self.calls = 0

    def validate(self, stock):
        self.calls += 1
        return super().validate(stock)


def test_orchestrator_owns_final_input_contract_gate():
    contract = SpyContract()
    orchestrator = EngineOrchestrator(engines=[], input_contract=contract)
    result = orchestrator.evaluate({})

    assert contract.calls == 1
    assert result["passed"] is False
    assert result["engines"] == {}
    assert "input_contract" in result


def test_invalid_direct_orchestrator_input_never_reaches_engine_execution():
    called = {"value": False}

    class Engine:
        NAME = "spy"
        mandatory = True

        def evaluate(self, stock):
            called["value"] = True
            raise AssertionError("engine execution should be blocked")

    orchestrator = EngineOrchestrator(engines=[Engine()])
    result = orchestrator.evaluate({"symbol": "ABC"})

    assert called["value"] is False
    assert result["passed"] is False
    assert result["engines"] == {}
