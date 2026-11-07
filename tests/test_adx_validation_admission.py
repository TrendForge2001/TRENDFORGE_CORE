"""Corrected indicators cannot reuse validation from the earlier registry."""

from types import SimpleNamespace

import pytest

from scanner.strategy_registry import REGISTRY_VERSION
from services.strategy_driven_paper_service import StrategyDrivenPaperService


@pytest.mark.parametrize(
    "version", [None, "source-six-with-five-intraday-shorts-v3", REGISTRY_VERSION]
)
def test_strategy_paper_admission_requires_current_calculation_evidence(version):
    strategy = "tf_swing_ema20_50_rsi_volume"
    scan = {
        "status": "completed",
        "run_id": "scan-1",
        "universe": "NIFTY 100",
        "mode": "swing",
        "requested_symbols": 100,
        "completed_symbols": 100,
        "error_symbols": 0,
        "top_picks": [],
    }
    validation = {
        "status": "completed",
        "run_id": "validation-1",
        "registry_version": version,
        "strategy_validation": [
            {
                "strategy_id": strategy,
                "mode": "swing",
                "promotion_status": "ELIGIBLE_FOR_REVIEW",
                "registry_paper_eligible": True,
                "universe_gates": [{"universe": "NIFTY 100", "status": "PASS"}],
            }
        ],
    }
    bridge = StrategyDrivenPaperService(
        scanner_service=SimpleNamespace(results=lambda: {"last_result": scan}),
        paper_auto_entry=SimpleNamespace(
            health=lambda: {"enabled": True},
            paper_service=SimpleNamespace(can_open_new_positions=True),
        ),
    )
    result = bridge.preview(
        strategy_id=strategy,
        scan_run_id="scan-1",
        validation_run_id="validation-1",
        validation_status=validation,
    )
    stale = version != REGISTRY_VERSION
    assert ("validation_registry_version_mismatch" in result["blockers"]) is stale
    assert result["status"] == ("blocked" if stale else "no_candidates")
    readiness = bridge.readiness(validation_status=validation)
    assert readiness["validation_registry_current"] is not stale
    assert readiness["eligible_strategy_count"] == (0 if stale else 1)
