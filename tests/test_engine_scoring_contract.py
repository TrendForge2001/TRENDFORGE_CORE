from __future__ import annotations

from engines.base_engine import EngineResult
from engines.engine_orchestrator import EngineOrchestrator


class FakeEngine:
    NAME = "Fake Engine"
    mandatory = False

    def __init__(self, score, max_score=100.0, confidence=50.0, passed=True):
        self.score = score
        self.max_score = max_score
        self.confidence = confidence
        self.passed = passed

    def evaluate(self, stock):
        return EngineResult(
            engine=self.NAME,
            passed=self.passed,
            score=self.score,
            max_score=self.max_score,
            confidence=self.confidence,
            grade="A",
        )


class FakeSignal:
    def generate_from_results(self, symbol, results):
        class Signal:
            signal = "BUY"
            warnings = []
        return Signal()


def test_engine_result_preserves_explicit_max_score():
    result = EngineResult("X", True, 25, 50, "B", max_score=40)
    assert result.as_dict()["max_score"] == 40
    assert result.as_dict()["score"] == 25


def test_orchestrator_clamps_out_of_range_scores_without_rewriting_engine_results():
    engine = FakeEngine(score=150, max_score=100)
    orchestrator = EngineOrchestrator(engines=[engine])
    orchestrator.signal_engine = FakeSignal()
    result = orchestrator.evaluate({"symbol": "ABC"})

    assert result["score"] == 100
    assert result["max_score"] == 100
    assert result["confidence"] == 100
    assert result["engines"]["Fake Engine"]["score"] == 150


def test_orchestrator_handles_zero_max_score():
    engine = FakeEngine(score=50, max_score=0)
    orchestrator = EngineOrchestrator(engines=[engine])
    orchestrator.signal_engine = FakeSignal()
    result = orchestrator.evaluate({"symbol": "ABC"})

    assert result["max_score"] == 0
    assert result["confidence"] == 0


def test_orchestrator_confidence_is_normalized_to_percent():
    orchestrator = EngineOrchestrator(
        engines=[FakeEngine(20, 40), FakeEngine(30, 60)]
    )
    orchestrator.signal_engine = FakeSignal()
    result = orchestrator.evaluate({"symbol": "ABC"})

    assert result["score"] == 50
    assert result["max_score"] == 100
    assert result["confidence"] == 50
