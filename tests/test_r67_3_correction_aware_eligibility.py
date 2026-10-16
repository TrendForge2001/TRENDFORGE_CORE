from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.full_pipeline import FullScannerPipeline
from services.paper_auto_entry_service import PaperAutoEntryService
from webapp.ui import scan_rows


def _pipeline() -> FullScannerPipeline:
    return FullScannerPipeline(provider=object())


def _signal(name: str, score: float, confidence: float = 70.0) -> dict:
    return {
        "signal": name,
        "overall_score": score,
        "confidence": confidence,
    }


def test_correction_and_incomplete_fundamentals_remain_analysis_rankable():
    result = {
        "symbol": "CORRECT",
        "passed": False,
        "signal": _signal("HOLD", 72.0, 68.0),
        "confidence": 68.0,
        "engines": {
            "Market Regime Engine": {
                "passed": False,
                "metrics": {"regime": "RISK_OFF"},
            },
            "Fundamental Engine": {
                "passed": False,
                "metrics": {"scoring_state": "INCOMPLETE"},
            },
        },
        "failed_mandatory": [
            "Market Regime Engine",
            "Fundamental Engine",
        ],
        "missing_mandatory": [],
        "execution_errors": [],
    }

    output = _pipeline()._finalize([result], top_n=20)
    ranked = output["analysis_top_picks"][0]

    assert output["eligibility_semantics_version"] == "R67.3"
    assert output["analysis_count"] == 1
    assert output["execution_count"] == 0
    assert output["top_picks"] == []
    assert ranked["analysis_eligible"] is True
    assert ranked["execution_eligible"] is False
    assert ranked["eligible"] is False
    assert ranked["analysis_rejection_reasons"] == []
    assert "mandatory_engine_failed" in ranked["execution_rejection_reasons"]
    assert ranked["decision_explainability"]["analysis_status"] == "RANKED"
    assert ranked["decision_explainability"]["execution_status"] == "BLOCKED"


def test_analysis_ranking_survives_non_buy_signals_and_orders_by_score():
    low = {
        "symbol": "LOW",
        "passed": False,
        "signal": _signal("HOLD", 41.0),
        "engines": {},
        "failed_mandatory": ["Fundamental Engine"],
        "missing_mandatory": [],
        "execution_errors": [],
    }
    high = {
        "symbol": "HIGH",
        "passed": True,
        "signal": _signal("REDUCE", 55.0),
        "engines": {},
        "failed_mandatory": [],
        "missing_mandatory": [],
        "execution_errors": [],
    }

    output = _pipeline()._finalize([low, high], top_n=20)

    assert [row["symbol"] for row in output["analysis_top_picks"]] == [
        "HIGH",
        "LOW",
    ]
    assert output["execution_top_picks"] == []
    assert output["analysis_count"] == 2
    assert output["execution_count"] == 0


def test_pipeline_failure_is_not_analysis_rankable():
    result = {
        "symbol": "BROKEN",
        "passed": False,
        "signal": "ERROR",
        "engines": {},
        "execution_errors": [],
        "error": "provider failed",
    }

    output = _pipeline()._finalize([result], top_n=20)

    assert output["analysis_count"] == 0
    assert output["execution_count"] == 0
    assert output["analysis_rejected_count"] == 1
    rejected = output["analysis_rejected"][0]
    assert rejected["analysis_eligible"] is False
    assert "pipeline_error" in rejected["analysis_rejection_reasons"]


def test_buy_that_passes_strict_gate_is_in_both_rankings():
    result = {
        "symbol": "ACTIONABLE",
        "passed": True,
        "signal": _signal("BUY", 93.0, 82.0),
        "confidence": 82.0,
        "engines": {},
        "failed_mandatory": [],
        "missing_mandatory": [],
        "execution_errors": [],
    }

    output = _pipeline()._finalize([result], top_n=20)

    assert output["analysis_top_picks"][0]["symbol"] == "ACTIONABLE"
    assert output["execution_top_picks"][0]["symbol"] == "ACTIONABLE"
    assert output["top_picks"][0]["symbol"] == "ACTIONABLE"
    assert output["count"] == 1
    assert output["execution_count"] == 1


class _ReadyPaper:
    can_open_new_positions = True


def test_paper_auto_entry_prefers_execution_top_picks_fail_closed():
    service = PaperAutoEntryService(_ReadyPaper(), enabled=True)
    analysis_only = {
        "symbol": "ANALYSISONLY",
        "signal": _signal("BUY", 99.0, 90.0),
        "analysis_eligible": True,
        "execution_eligible": False,
        "eligible": False,
    }

    output = service.process_scan(
        {
            "outcome": "completed",
            "analysis_top_picks": [analysis_only],
            "top_picks": [analysis_only],
            "execution_top_picks": [],
        },
        run_id="r67-3",
        execute_requested=True,
        now=datetime(2026, 10, 16, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
    )

    assert output["status"] == "no_entries"
    assert output["candidate_count"] == 0
    assert output["evaluation_count"] == 0
    assert output["opened_count"] == 0


def test_webapp_prefers_analysis_top_picks_and_exposes_both_gates():
    payload = {
        "analysis_top_picks": [
            {
                "symbol": "WATCH",
                "signal": _signal("HOLD", 71.0, 66.0),
                "analysis_eligible": True,
                "execution_eligible": False,
                "execution_rejection_reason": "mandatory_engine_failed",
                "eligible": False,
            }
        ],
        "top_picks": [],
    }

    rows = scan_rows(payload)

    assert len(rows) == 1
    assert rows[0]["Symbol"] == "WATCH"
    assert rows[0]["Analysis Eligible"] is True
    assert rows[0]["Execution Eligible"] is False
    assert rows[0]["Eligible"] is False
    assert rows[0]["Execution Block"] == "mandatory_engine_failed"
