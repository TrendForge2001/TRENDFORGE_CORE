from __future__ import annotations

from engines.engine_orchestrator import EngineOrchestrator


class _EngineWithoutEvaluate:
    NAME = "Broken Engine"


class _SignalWithoutMethods:
    NAME = "Broken Signal Engine"


def test_health_reports_invalid_engine_and_signal_contracts():
    orchestrator = EngineOrchestrator(
        engines=[_EngineWithoutEvaluate()],
        input_contract=None,
    )
    orchestrator.signal_engine = _SignalWithoutMethods()

    health = orchestrator.health()

    assert health["status"] == "degraded"
    assert health["invalid_engines"] == ["Broken Engine"]
    assert health["invalid_signal_methods"] == ["generate_from_results", "evaluate"]
    assert health["signal_methods"] == {
        "generate_from_results": False,
        "evaluate": False,
    }


def test_default_health_exposes_signal_contract_methods():
    health = EngineOrchestrator().health()

    assert health["status"] == "configured"
    assert health["signal_methods"] == {
        "generate_from_results": True,
        "evaluate": True,
    }
