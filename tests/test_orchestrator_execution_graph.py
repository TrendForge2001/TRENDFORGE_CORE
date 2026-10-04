from __future__ import annotations

import inspect

from engines.engine_orchestrator import EngineOrchestrator


def test_orchestrator_has_single_engine_execution_loop():
    source = inspect.getsource(EngineOrchestrator.evaluate)
    assert source.count("engine.evaluate(stock)") == 1
    assert "for engine in self.engines" in source


def test_orchestrator_owns_signal_aggregation_once():
    source = inspect.getsource(EngineOrchestrator.evaluate)
    assert source.count("generate_from_results(symbol, results)") == 1


def test_orchestrator_has_no_nested_orchestrator_execution():
    source = inspect.getsource(EngineOrchestrator)
    assert "EngineOrchestrator(" not in source.split("def evaluate", 1)[-1]
    assert "IndicatorEngine(" not in source.split("def evaluate", 1)[-1]


def test_orchestrator_health_reports_canonical_graph():
    health = EngineOrchestrator().health()
    assert health["status"] == "configured"
    assert health["engine_count"] == len(health["engines"])
    assert health["engine_count"] > 0
