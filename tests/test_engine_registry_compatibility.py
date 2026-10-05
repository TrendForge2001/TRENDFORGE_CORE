from __future__ import annotations

from engines.engine_orchestrator import EngineOrchestrator
from pipeline.engine_registry import EngineRegistry


class StubEngine:
    NAME = "Stub Engine"
    mandatory = True

    def evaluate(self, stock):
        raise AssertionError("EngineRegistry must not execute engines directly")


def test_registry_delegates_execution_to_orchestrator():
    registry = EngineRegistry(orchestrator=object())
    assert registry.orchestrator is not None


def test_registry_registers_without_own_execution_path():
    registry = EngineRegistry(orchestrator=object())
    engine = StubEngine()
    registry.register(engine)
    assert registry.engines == [engine]


def test_registry_uses_supplied_orchestrator():
    orchestrator = EngineOrchestrator(engines=[])
    registry = EngineRegistry(orchestrator=orchestrator)
    assert registry.orchestrator is orchestrator
