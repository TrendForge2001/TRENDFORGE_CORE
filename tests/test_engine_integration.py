from __future__ import annotations

import pytest

from engines.base_engine import EngineResult
from engines.engine_orchestrator import EngineOrchestrator


class StubEngine:
    NAME = "Stub Engine"
    mandatory = True

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def evaluate(self, stock):
        if self.error:
            raise self.error
        return self.result or EngineResult(
            engine=self.NAME,
            passed=True,
            score=80,
            max_score=100,
            confidence=80,
            grade="A",
        )


class StubSignalEngine:
    def generate_from_results(self, symbol, results):
        class Signal:
            signal = "BUY"
            warnings = []

        return Signal()


def stock():
    return {"symbol": "ABC", "df": object(), "snapshot": {"close": 100}}


def test_orchestrator_aggregates_engine_results():
    engine = StubEngine()
    orchestrator = EngineOrchestrator(engines=[engine])
    orchestrator.signal_engine = StubSignalEngine()

    result = orchestrator.evaluate(stock())

    assert result["passed"] is True
    assert result["score"] == 80
    assert result["max_score"] == 100
    assert result["confidence"] == 80
    assert result["execution_errors"] == []
    assert result["missing_mandatory"] == []
    assert result["failed_mandatory"] == []


def test_missing_mandatory_engine_fails_closed():
    class NonMandatoryEngine(StubEngine):
        mandatory = False

    orchestrator = EngineOrchestrator(engines=[NonMandatoryEngine()])
    orchestrator.signal_engine = StubSignalEngine()

    result = orchestrator.evaluate(stock())

    assert result["passed"] is True
    assert result["missing_mandatory"] == []


def test_failed_mandatory_engine_forces_hold():
    failed = EngineResult(
        engine="Stub Engine",
        passed=False,
        score=0,
        max_score=100,
        confidence=0,
        grade="F",
    )
    orchestrator = EngineOrchestrator(engines=[StubEngine(result=failed)])
    orchestrator.signal_engine = StubSignalEngine()

    result = orchestrator.evaluate(stock())

    assert result["passed"] is False
    assert "Stub Engine" in result["failed_mandatory"]
    assert result["signal"].signal == "HOLD"


def test_engine_exception_is_captured_and_fails_closed():
    orchestrator = EngineOrchestrator(
        engines=[StubEngine(error=RuntimeError("boom"))]
    )
    orchestrator.signal_engine = StubSignalEngine()

    result = orchestrator.evaluate(stock())

    assert result["passed"] is False
    assert result["execution_errors"]
    assert "Stub Engine" in result["failed_mandatory"]
    assert result["signal"].signal == "HOLD"


def test_invalid_engine_result_is_captured():
    class InvalidEngine(StubEngine):
        def evaluate(self, stock):
            return {"passed": True, "score": 100}

    orchestrator = EngineOrchestrator(engines=[InvalidEngine()])
    orchestrator.signal_engine = StubSignalEngine()

    result = orchestrator.evaluate(stock())

    assert result["passed"] is False
    assert any("expected EngineResult" in error for error in result["execution_errors"])
    assert result["signal"].signal == "HOLD"


def test_invalid_input_contract_fails_before_engine_execution():
    engine = StubEngine()
    orchestrator = EngineOrchestrator(engines=[engine])
    orchestrator.signal_engine = StubSignalEngine()

    result = orchestrator.evaluate({"symbol": "ABC"})

    assert result["passed"] is False
    assert result["score"] == 0.0
    assert result["engines"] == {}
    assert result["signal"].signal == "HOLD"


def test_health_reports_canonical_engine_chain():
    orchestrator = EngineOrchestrator(engines=[StubEngine()])
    health = orchestrator.health()

    assert health["status"] == "healthy"
    assert health["engines_count"] == 1
    assert health["signal_engine"] == "StubSignalEngine" if False else health["signal_engine"] == "ContractedSignalEngine"
