from __future__ import annotations

from core.pipeline import TrendForgePipeline
from engines.base_engine import EngineResult
from engines.engine_orchestrator import EngineOrchestrator


class StubEngine:
    NAME = "Stub Engine"
    mandatory = True

    def evaluate(self, stock):
        return EngineResult(
            engine=self.NAME,
            passed=True,
            score=75.0,
            max_score=100.0,
            confidence=75.0,
            grade="B",
        )


def test_core_pipeline_delegates_to_orchestrator():
    orchestrator = EngineOrchestrator(engines=[StubEngine()])
    pipeline = TrendForgePipeline(orchestrator=orchestrator)

    result = pipeline.execute({"symbol": "ABC", "df": None})

    assert result["score"] == 0.0 or result["score"] == 75.0
    assert "results" in result
    assert "input_contract" in result


def test_core_pipeline_registration_uses_orchestrator_engine_collection():
    orchestrator = EngineOrchestrator(engines=[])
    pipeline = TrendForgePipeline(orchestrator=orchestrator)
    engine = StubEngine()

    pipeline.register(engine)

    assert pipeline.engines is orchestrator.engines
    assert orchestrator.engines[-1] is engine


def test_core_pipeline_health_delegates():
    orchestrator = EngineOrchestrator(engines=[])
    pipeline = TrendForgePipeline(orchestrator=orchestrator)

    assert pipeline.health() == orchestrator.health()
