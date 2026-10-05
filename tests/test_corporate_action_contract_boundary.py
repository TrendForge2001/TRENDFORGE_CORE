from __future__ import annotations

from engines.base_engine import EngineResult
from engines.contracted_corporate_action_engine import ContractedCorporateActionEngine
from engines.corporate_action_contract import CorporateActionInputContract


class SpyEngine:
    NAME = "Corporate Action Engine"
    priority = 4
    mandatory = False

    def __init__(self):
        self.called = False

    def evaluate(self, stock):
        self.called = True
        return EngineResult(
            engine=self.NAME,
            passed=True,
            score=70.0,
            max_score=100.0,
            confidence=80.0,
            grade="B",
        )


def test_corporate_action_contract_rejects_malformed_event_payload_before_execution():
    engine = SpyEngine()
    contracted = ContractedCorporateActionEngine(engine=engine)

    result = contracted.evaluate({"symbol": "ABC", "events": "not-a-list"})

    assert engine.called is False
    assert result.passed is False
    assert result.metrics["input_contract"]["ready"] is False


def test_corporate_action_contract_allows_symbol_without_inline_events():
    engine = SpyEngine()
    contracted = ContractedCorporateActionEngine(engine=engine)

    result = contracted.evaluate({"symbol": "ABC"})

    assert engine.called is True
    assert result.passed is True
    assert result.metrics["input_contract"]["ready"] is True
    assert result.metrics["input_contract"]["warnings"]


def test_corporate_action_contract_is_owned_by_contracted_engine():
    contracted = ContractedCorporateActionEngine(engine=SpyEngine())
    assert isinstance(contracted.input_contract, CorporateActionInputContract)
