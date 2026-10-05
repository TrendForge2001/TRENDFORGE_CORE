from __future__ import annotations

from scanner.full_pipeline import FullScannerPipeline


def test_hard_risk_has_deterministic_reason():
    result = {
        "passed": False,
        "signal": "HOLD",
        "engines": {"Risk Engine": {"metrics": {"hard_block": True}}},
    }
    reasons = FullScannerPipeline._rejection_reasons(result)
    assert "orchestrator_failed" in reasons
    assert "negative_signal:hold" in reasons
    assert "hard_risk_block" in reasons


def test_negative_signal_is_rejected_without_hard_block():
    result = {"passed": True, "signal": "SELL", "engines": {}}
    reasons = FullScannerPipeline._rejection_reasons(result)
    assert reasons == ["negative_signal:sell"]
    assert FullScannerPipeline._is_eligible(result) is False


def test_execution_error_is_visible():
    result = {"passed": False, "signal": "ERROR", "engines": {}, "execution_errors": ["Risk Engine: failed"]}
    reasons = FullScannerPipeline._rejection_reasons(result)
    assert "engine_execution_error" in reasons
    assert "negative_signal:error" in reasons


def test_finalize_ranks_only_eligible_results_and_preserves_rejection_metadata():
    results = [
        {"symbol": "BAD", "passed": False, "signal": "HOLD", "score": 100, "confidence": 100, "engines": {}},
        {"symbol": "GOOD", "passed": True, "signal": "BUY", "score": 80, "confidence": 70, "engines": {}},
    ]
    output = FullScannerPipeline._finalize(object.__new__(FullScannerPipeline), results, top_n=20)
    assert [item["symbol"] for item in output["top_picks"]] == ["GOOD"]
    assert output["rejected"][0]["symbol"] == "BAD"
    assert output["rejected"][0]["rejection_reason"] == "orchestrator_failed"
    assert output["rejected_count"] == 1
