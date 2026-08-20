from __future__ import annotations

from pathlib import Path

# Contract tests currently maintained on the reconstruction branch.  The index
# intentionally covers only files that are present in this branch.
CONTRACT_GROUPS = {
    "application": {
        "test_api_entrypoint_canonical_boundary.py",
        "test_api_provider_boundary.py",
        "test_application_construction_boundaries.py",
        "test_application_end_to_end_contract.py",
        "test_application_factory.py",
        "test_release_readiness_contract.py",
        "test_main_branch_reconciliation_contract.py",
    },
    "data": {
        "test_core_data_contract_reconciliation.py",
        "test_nontechnical_payload_ownership.py",
        "test_payload_only_execution_mode.py",
    },
    "providers": {
        "test_provider_contracts.py",
        "test_provider_factory.py",
    },
    "indicators": {
        "test_indicator_engine_contract.py",
        "test_canonical_indicator_facades.py",
        "test_indicator_owner_contract.py",
    },
    "engines": {
        "test_canonical_technical_engine.py",
        "test_orchestrator_execution_graph.py",
        "test_big_shark_data_ownership.py",
        "test_engine_contracts.py",
        "test_engine_contract_depth.py",
        "test_engine_scoring_contract.py",
        "test_engine_hard_risk_veto.py",
        "test_signal_orchestrator_decision_matrix.py",
    },
    "scanner": {
        "test_pipeline_contracts.py",
        "test_legacy_scanner_boundary.py",
        "test_core_pipeline_compatibility.py",
        "test_end_to_end_single_execution.py",
        "test_full_scanner_decision_propagation.py",
        "test_scanner_rejection_reasons.py",
    },
}


def test_contract_suite_index_has_no_missing_files():
    root = Path(__file__).parent
    missing = [
        name
        for names in CONTRACT_GROUPS.values()
        for name in names
        if not (root / name).exists()
    ]
    assert not missing, f"Indexed contract tests missing: {missing}"


def test_contract_suite_index_has_no_duplicate_assignments():
    assignments = {}
    duplicates = []
    for group, names in CONTRACT_GROUPS.items():
        for name in names:
            if name in assignments:
                duplicates.append((name, assignments[name], group))
            assignments[name] = group
    assert not duplicates, f"Tests assigned to multiple contract groups: {duplicates}"
