from __future__ import annotations

from engines.canonical_nontechnical_engines import (
    CanonicalBigSharkEngine,
    CanonicalSectorEngine,
    CanonicalCorporateActionEngine,
)
from engines.engine_orchestrator import EngineOrchestrator


def test_canonical_engines_use_payload_only_dependencies():
    assert CanonicalBigSharkEngine().provider is not None
    assert CanonicalBigSharkEngine().repository is not None
    assert CanonicalSectorEngine().provider is not None
    assert CanonicalSectorEngine().repository is not None
    assert CanonicalCorporateActionEngine().provider is not None
    assert CanonicalCorporateActionEngine().repository is not None


def test_orchestrator_uses_payload_only_nontechnical_engines():
    orchestrator = EngineOrchestrator()
    names = {engine.engine.__class__.__name__ for engine in orchestrator.engines if hasattr(engine, "engine")}
    assert "CanonicalBigSharkEngine" in names
    assert "CanonicalSectorEngine" in names
    assert "CanonicalCorporateActionEngine" in names


def test_payload_only_dependency_does_not_fetch():
    from engines.canonical_data_execution import PAYLOAD_ONLY
    assert PAYLOAD_ONLY.get_shareholding("ABC") is None
    assert PAYLOAD_ONLY.get_sector_snapshot("ABC") is None
    assert PAYLOAD_ONLY.get_corporate_actions("ABC") is None
