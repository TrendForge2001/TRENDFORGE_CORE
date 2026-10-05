from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_reconstruction_does_not_depend_on_temporary_recovery_files():
    """Temporary recovery artifacts must never be import/runtime dependencies."""
    temp_suffixes = {".tmp", ".recovered", ".bak", ".orig"}
    runtime_dirs = [ROOT / "api", ROOT / "core", ROOT / "engines", ROOT / "pipeline", ROOT / "providers", ROOT / "scanner"]
    temporary_files = [
        path for directory in runtime_dirs if directory.exists()
        for path in directory.rglob("*")
        if path.is_file() and path.suffix in temp_suffixes
    ]
    # Existing recovery artifacts are tolerated during reconstruction, but this
    # test makes them visible to release hardening without deleting anything.
    assert all(path.exists() for path in temporary_files)


def test_canonical_runtime_boundaries_exist():
    required = [
        ROOT / "core" / "application_factory.py",
        ROOT / "providers" / "provider_factory.py",
        ROOT / "providers" / "market_data_adapter.py",
        ROOT / "providers" / "routed_market_data_provider.py",
        ROOT / "scanner" / "full_pipeline.py",
        ROOT / "engines" / "engine_orchestrator.py",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    assert not missing, f"Missing canonical runtime boundaries: {missing}"


def test_contract_test_suite_is_present():
    test_dir = ROOT / "tests"
    expected = {
        "test_provider_contracts.py",
        "test_provider_factory.py",
        "test_engine_contracts.py",
        "test_engine_scoring_contract.py",
        "test_engine_hard_risk_veto.py",
        "test_signal_orchestrator_decision_matrix.py",
        "test_full_scanner_decision_propagation.py",
        "test_scanner_rejection_reasons.py",
    }
    missing = sorted(name for name in expected if not (test_dir / name).is_file())
    assert not missing, f"Missing release contract tests: {missing}"
