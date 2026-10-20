from __future__ import annotations

from webapp.scan_workflow import (
    continuation_from_result,
    continuation_is_resumable,
    fundamental_gap_rows,
    lineage_run_rows,
    scan_history_rows,
)


def test_fundamental_gap_rows_compact_scanner_payload():
    rows = fundamental_gap_rows({
        "symbol_results": [
            {
                "symbol": "AAA",
                "fundamental_readiness": {
                    "status": "DATA_INCOMPLETE",
                    "missing_fields": ["roe", "eps_growth"],
                    "invalid_fields": [],
                },
                "primary_execution_block": "fundamental:data_incomplete",
            },
            {
                "symbol": "BBB",
                "fundamental_readiness": {"status": "READY_FAIL_QUALITY"},
            },
            {
                "symbol": "CCC",
                "fundamental_readiness": {
                    "status": "INVALID",
                    "invalid_fields": ["debt_equity"],
                },
            },
        ]
    })
    assert [row["Symbol"] for row in rows] == ["AAA", "CCC"]
    assert rows[0]["Missing fields"] == "roe, eps_growth"
    assert rows[1]["Invalid fields"] == "debt_equity"


def test_fundamental_gap_rows_noncompact_deduplicates_and_keeps_detail():
    rows = fundamental_gap_rows({
        "analysis_ranked": [
            {"symbol": "ABC", "fundamental_readiness": {
                "status": "DATA_INCOMPLETE", "missing_fields": [],
            }},
        ],
        "execution_rejected": [
            {"symbol": "abc", "fundamental_readiness": {
                "status": "DATA_INCOMPLETE", "missing_fields": ["roce", "roe"],
            }},
        ],
    })
    assert len(rows) == 1
    assert rows[0]["Symbol"] == "ABC"
    assert rows[0]["Missing fields"] == "roce, roe"
    assert fundamental_gap_rows({"symbol_results": None}) == []


def test_continuation_prefers_rich_response_contract():
    result = {
        "continuation": {
            "token": "opaque",
            "status": "pending",
            "generation": 2,
            "symbol_count": 17,
        },
        "scale_gate": {
            "continuation_token": "fallback",
        },
    }

    continuation = continuation_from_result(result)

    assert continuation is not None
    assert continuation["token"] == "opaque"
    assert continuation["generation"] == 2


def test_continuation_falls_back_to_scale_gate():
    result = {
        "scale_gate": {
            "continuation_token": "opaque",
            "next_continuation_generation": 1,
            "continuation_symbol_count": 25,
            "next_continuation_expires_at": "future",
        }
    }

    continuation = continuation_from_result(result)

    assert continuation == {
        "token": "opaque",
        "status": "pending",
        "generation": 1,
        "symbol_count": 25,
        "expires_at": "future",
    }


def test_resume_requires_pending_status_and_attempt_budget():
    assert continuation_is_resumable(
        {
            "effective_status": "pending",
            "claim_attempts_remaining": 2,
        }
    )
    assert not continuation_is_resumable(
        {
            "effective_status": "consumed",
            "claim_attempts_remaining": 2,
        }
    )
    assert not continuation_is_resumable(
        {
            "effective_status": "pending",
            "claim_attempts_remaining": 0,
        }
    )


def test_scan_history_rows_flattens_audit_metadata():
    rows = scan_history_rows(
        {
            "runs": [
                {
                    "run_id": "run-1",
                    "outcome": "partial",
                    "requested_symbols": 50,
                    "completed_symbols": 25,
                    "error_symbols": 0,
                    "missing_symbols": 0,
                    "metadata": {
                        "processed_symbols": 25,
                        "accounted_pct": 50.0,
                        "scan_budget_utilization_pct": 100.0,
                        "next_continuation_available": True,
                    },
                }
            ]
        }
    )

    assert rows[0]["Run ID"] == "run-1"
    assert rows[0]["Outcome"] == "PARTIAL"
    assert rows[0]["Processed"] == 25
    assert rows[0]["Completion %"] == 50.0
    assert rows[0]["Next resume"] is True


def test_lineage_rows_match_attempt_rollup_contract():
    rows = lineage_run_rows(
        {
            "attempt_runs": [
                {
                    "run_id": "child",
                    "outcome": "rejected",
                    "http_status": 409,
                    "failure_stage": "admission",
                }
            ]
        }
    )

    assert rows[0]["Run ID"] == "child"
    assert rows[0]["Outcome"] == "REJECTED"
    assert rows[0]["HTTP"] == 409
    assert rows[0]["Failure stage"] == "admission"
    assert rows[0]["View"] == "attempt"
