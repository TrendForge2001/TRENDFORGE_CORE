from __future__ import annotations

from core.engine_registry import EngineRegistry


class StubEngine:
    NAME = "Stub Engine"


def test_core_registry_is_non_executing_lookup_compatibility_layer():
    registry = EngineRegistry()
    engine = StubEngine()
    registry.register(engine.NAME, engine)

    assert registry.get(engine.NAME) is engine
    assert list(registry.all()) == [engine]


def test_core_registry_has_no_engine_execution_method():
    registry = EngineRegistry()
    assert not hasattr(registry, "execute")
    assert not hasattr(registry, "evaluate")
