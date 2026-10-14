from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from core.database import initialize_database
from database.database import Database
from database.repositories.scan_continuation_repository import (
    ScanContinuationRepository,
)
from database.repositories.scan_run_audit_repository import (
    ScanRunAuditRepository,
)
from services.scan_continuation_service import ScanContinuationService
from services.scan_run_audit_service import ScanRunAuditService
from services.scan_lineage_service import (
    ScanLineageNotFoundError,
    ScanLineageService,
)


def _audit(
    run_id,
    *,
    outcome,
    requested,
    completed,
    processed,
    root,
    audit_id,
    parent=None,
    sla_met=True,
    failure_stage=None,
    continuation_limit_reason=None,
    generation=None,
):
    return {
        "id": audit_id,
        "run_id": run_id,
        "scan_type": "nifty500",
        "outcome": outcome,
        "http_status": 200 if outcome != "rejected" else 409,
        "failure_stage": failure_stage,
        "started_at": f"2026-10-14T10:0{audit_id}:00+00:00",
        "finished_at": f"2026-10-14T10:0{audit_id}:20+00:00",
        "duration_sec": 20.0,
        "requested_symbols": requested,
        "completed_symbols": completed,
        "error_symbols": max(0, requested - completed),
        "missing_symbols": 0,
        "fallback_count": 0,
        "nse_resolution_count": 0,
        "metadata": {
            "processed_symbols": processed,
            "is_continuation": parent is not None,
            "lineage_root_run_id": root,
            "parent_run_id": parent,
            "continuation_generation": (
                generation
                if generation is not None
                else 1
                if parent is not None
                else 0
            ),
            "sla_met": sla_met,
            "sla_status": "met" if sla_met else "breached",
            "continuation_limit_reason": continuation_limit_reason,
        },
    }


class FakeAuditLineageService:
    def __init__(self, records):
        self.records = {
            item["run_id"]: dict(item)
            for item in records
        }

    def get(self, run_id):
        record = self.records.get(str(run_id))
        return dict(record) if record else None

    def lineage(self, root_run_id):
        return [
            dict(item)
            for item in self.records.values()
            if item["run_id"] == root_run_id
            or item.get("metadata", {}).get(
                "lineage_root_run_id"
            ) == root_run_id
        ]


class FakeContinuationLineageService:
    def __init__(self, records):
        self.records = [dict(item) for item in records]

    def lineage(self, root_run_id):
        return [
            dict(item)
            for item in self.records
            if item.get("lineage_root_run_id") == root_run_id
        ]


def _continuation(
    *,
    parent,
    root,
    generation,
    status,
    symbols,
    child=None,
    expires_at="2099-01-01T00:00:00+00:00",
    attempts=1,
    maximum=3,
):
    return {
        "parent_run_id": parent,
        "lineage_root_run_id": root,
        "generation": generation,
        "status": status,
        "symbols": list(symbols),
        "child_run_id": child,
        "created_at": "2026-10-14T10:00:20+00:00",
        "claimed_at": (
            "2026-10-14T10:01:00+00:00"
            if status in {"active", "consumed"}
            else None
        ),
        "consumed_at": (
            "2026-10-14T10:02:00+00:00"
            if status == "consumed"
            else None
        ),
        "expires_at": expires_at,
        "claim_attempts": attempts,
        "max_claim_attempts": maximum,
        "recovery_count": 0,
    }


def test_completed_lineage_rollup_uses_only_committed_path():
    root = _audit(
        "root",
        outcome="partial",
        requested=50,
        completed=25,
        processed=25,
        root="root",
        audit_id=1,
        sla_met=False,
    )
    failed_attempt = _audit(
        "failed-child",
        outcome="failed",
        requested=25,
        completed=0,
        processed=0,
        root="root",
        audit_id=2,
        parent="root",
        sla_met=False,
        failure_stage="scan_execution",
    )
    child = _audit(
        "child",
        outcome="completed",
        requested=25,
        completed=25,
        processed=25,
        root="root",
        audit_id=3,
        parent="root",
        sla_met=True,
    )
    replay = _audit(
        "replay",
        outcome="rejected",
        requested=25,
        completed=0,
        processed=0,
        root="root",
        audit_id=4,
        parent="root",
        sla_met=True,
        failure_stage="continuation_validation",
    )

    audit = FakeAuditLineageService(
        [root, failed_attempt, child, replay]
    )
    continuation = FakeContinuationLineageService(
        [
            _continuation(
                parent="root",
                root="root",
                generation=1,
                status="consumed",
                symbols=[f"SYM{i}" for i in range(25)],
                child="child",
            )
        ]
    )

    result = ScanLineageService(audit, continuation).rollup(
        "child"
    )

    assert result["requested_run_id"] == "child"
    assert result["lineage_root_run_id"] == "root"
    assert result["status"] == "completed"
    assert result["terminal"] is True
    assert result["root_requested_symbols"] == 50
    assert result["cumulative_completed_symbols"] == 50
    assert result["cumulative_processed_symbols"] == 50
    assert result["remaining_symbols"] == 0
    assert result["end_to_end_completion_pct"] == 100.0
    assert result["end_to_end_processed_pct"] == 100.0
    assert result["committed_run_count"] == 2
    assert result["attempt_run_count"] == 4
    assert [
        item["run_id"] for item in result["committed_runs"]
    ] == ["root", "child"]
    assert result["lineage_sla_status"] == "breached"
    assert result["continuations"][0]["status"] == "consumed"
    assert result["integrity_status"] == "healthy"
    assert result["integrity_issue_count"] == 0
    assert result["integrity"]["valid"] is True


def test_pending_continuation_reports_resumable_progress():
    root = _audit(
        "root",
        outcome="partial",
        requested=50,
        completed=25,
        processed=25,
        root="root",
        audit_id=1,
        sla_met=False,
    )
    service = ScanLineageService(
        FakeAuditLineageService([root]),
        FakeContinuationLineageService(
            [
                _continuation(
                    parent="root",
                    root="root",
                    generation=1,
                    status="pending",
                    symbols=[f"SYM{i}" for i in range(25)],
                    attempts=0,
                )
            ]
        ),
    )

    result = service.rollup("root")

    assert result["status"] == "resumable"
    assert result["terminal"] is False
    assert result["cumulative_completed_symbols"] == 25
    assert result["remaining_symbols"] == 25
    assert result["end_to_end_completion_pct"] == 50.0


def test_expired_continuation_reports_blocked():
    root = _audit(
        "root",
        outcome="partial",
        requested=50,
        completed=25,
        processed=25,
        root="root",
        audit_id=1,
        sla_met=False,
    )
    service = ScanLineageService(
        FakeAuditLineageService([root]),
        FakeContinuationLineageService(
            [
                _continuation(
                    parent="root",
                    root="root",
                    generation=1,
                    status="pending",
                    symbols=["AAA"],
                    expires_at="2020-01-01T00:00:00+00:00",
                    attempts=0,
                )
            ]
        ),
    )

    result = service.rollup("root")

    assert result["status"] == "blocked"
    assert result["terminal"] is True
    assert result["continuations"][0]["effective_status"] == "expired"


def test_max_depth_partial_lineage_reports_blocked_with_remaining_symbols():
    root = _audit(
        "root",
        outcome="partial",
        requested=50,
        completed=25,
        processed=25,
        root="root",
        audit_id=1,
        sla_met=False,
    )
    child = _audit(
        "generation-4-child",
        outcome="partial",
        requested=25,
        completed=12,
        processed=12,
        root="root",
        audit_id=2,
        parent="root",
        sla_met=False,
        continuation_limit_reason="maximum_generation_reached",
        generation=4,
    )
    service = ScanLineageService(
        FakeAuditLineageService([root, child]),
        FakeContinuationLineageService(
            [
                _continuation(
                    parent="root",
                    root="root",
                    generation=4,
                    status="consumed",
                    symbols=[f"SYM{i}" for i in range(25)],
                    child="generation-4-child",
                )
            ]
        ),
    )

    result = service.rollup("root")

    assert result["status"] == "blocked"
    assert result["terminal"] is True
    assert result["cumulative_completed_symbols"] == 37
    assert result["remaining_symbols"] == 13
    assert result["end_to_end_completion_pct"] == 74.0


def test_lineage_endpoint_accepts_child_run_id_and_returns_root_rollup():
    root = _audit(
        "root",
        outcome="partial",
        requested=50,
        completed=25,
        processed=25,
        root="root",
        audit_id=1,
        sla_met=False,
    )
    child = _audit(
        "child",
        outcome="completed",
        requested=25,
        completed=25,
        processed=25,
        root="root",
        audit_id=2,
        parent="root",
    )
    audit = FakeAuditLineageService([root, child])
    continuation = FakeContinuationLineageService(
        [
            _continuation(
                parent="root",
                root="root",
                generation=1,
                status="consumed",
                symbols=[f"SYM{i}" for i in range(25)],
                child="child",
            )
        ]
    )

    class Factory:
        def scan_run_audit_service(self):
            return audit

        def scan_continuation_service(self):
            return continuation

    response = TestClient(create_app(Factory())).get(
        "/observability/scan-lineages/child"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requested_run_id"] == "child"
    assert body["lineage_root_run_id"] == "root"
    assert body["status"] == "completed"
    assert body["end_to_end_completion_pct"] == 100.0


def test_lineage_endpoint_returns_404_for_unknown_run():
    audit = FakeAuditLineageService([])
    continuation = FakeContinuationLineageService([])

    class Factory:
        def scan_run_audit_service(self):
            return audit

        def scan_continuation_service(self):
            return continuation

    response = TestClient(create_app(Factory())).get(
        "/observability/scan-lineages/missing"
    )

    assert response.status_code == 404



def test_real_sqlite_lineage_survives_rejected_replay_attempt(tmp_path: Path):
    db_path = tmp_path / "lineage-replay.db"
    initialize_database(str(db_path))

    audit_db = Database(str(db_path))
    continuation_db = Database(str(db_path))
    audit_repo = ScanRunAuditRepository(db=audit_db)
    continuation_repo = ScanContinuationRepository(continuation_db)
    audit_service = ScanRunAuditService(audit_repo)
    continuation_service = ScanContinuationService(
        repository=continuation_repo
    )

    try:
        root_id = "root-real"
        child_id = "child-real"
        replay_id = "replay-real"

        audit_service.record(
            {
                "run_id": root_id,
                "scan_type": "nifty500",
                "outcome": "partial",
                "http_status": 200,
                "failure_stage": "time_budget",
                "failure_message": "batch_time_budget_exceeded",
                "started_at": "2026-10-14T10:00:00+00:00",
                "finished_at": "2026-10-14T10:00:20+00:00",
                "duration_sec": 20.0,
                "requested_symbols": 50,
                "completed_symbols": 25,
                "error_symbols": 25,
                "missing_symbols": 0,
                "enrichment_failures": 0,
                "execution_errors": 0,
                "full_universe": False,
                "provider_counts": {"KiteProvider": 25},
                "fallback_count": 0,
                "nse_resolution_count": 0,
                "error_details": {},
                "metadata": {
                    "processed_symbols": 25,
                    "is_continuation": False,
                    "lineage_root_run_id": root_id,
                    "parent_run_id": None,
                    "continuation_generation": 0,
                    "sla_met": False,
                    "sla_status": "breached",
                },
            }
        )

        continuation = continuation_repo.create(
            token="real-token",
            parent_run_id=root_id,
            lineage_root_run_id=root_id,
            generation=1,
            symbols=[f"SYM{i}" for i in range(25, 50)],
            request={"period": "6mo", "interval": "1d"},
            ttl_seconds=3600,
            max_claim_attempts=3,
        )
        assert continuation["status"] == "pending"

        continuation_repo.claim("real-token", child_id)

        audit_service.record(
            {
                "run_id": child_id,
                "scan_type": "nifty500",
                "outcome": "completed",
                "http_status": 200,
                "failure_stage": None,
                "failure_message": None,
                "started_at": "2026-10-14T10:01:00+00:00",
                "finished_at": "2026-10-14T10:01:20+00:00",
                "duration_sec": 20.0,
                "requested_symbols": 25,
                "completed_symbols": 25,
                "error_symbols": 0,
                "missing_symbols": 0,
                "enrichment_failures": 0,
                "execution_errors": 0,
                "full_universe": False,
                "provider_counts": {"KiteProvider": 25},
                "fallback_count": 0,
                "nse_resolution_count": 0,
                "error_details": {},
                "metadata": {
                    "processed_symbols": 25,
                    "is_continuation": True,
                    "lineage_root_run_id": root_id,
                    "parent_run_id": root_id,
                    "continuation_generation": 1,
                    "sla_met": True,
                    "sla_status": "met",
                },
            }
        )
        continuation_repo.consume("real-token", child_id)

        # This is the exact production regression trigger: immutable rejected
        # replay audit after the committed child has already consumed token.
        audit_service.record(
            {
                "run_id": replay_id,
                "scan_type": "nifty500",
                "outcome": "rejected",
                "http_status": 409,
                "failure_stage": "continuation_validation",
                "failure_message": (
                    "Scan continuation token is not pending"
                ),
                "started_at": "2026-10-14T10:02:00+00:00",
                "finished_at": "2026-10-14T10:02:00+00:00",
                "duration_sec": 0.0,
                "requested_symbols": 25,
                "completed_symbols": 0,
                "error_symbols": 0,
                "missing_symbols": 0,
                "enrichment_failures": 0,
                "execution_errors": 0,
                "full_universe": False,
                "provider_counts": {},
                "fallback_count": 0,
                "nse_resolution_count": 0,
                "error_details": {},
                "metadata": {
                    "is_continuation": True,
                    "parent_run_id": root_id,
                    "lineage_root_run_id": root_id,
                    "continuation_generation": 1,
                    "continuation_status": "consumed",
                    "existing_child_run_id": child_id,
                    "claim_attempts": 1,
                    "max_claim_attempts": 3,
                },
            }
        )

        result = ScanLineageService(
            audit_service,
            continuation_service,
        ).rollup(root_id)

        assert result["status"] == "completed"
        assert result["terminal"] is True
        assert result["cumulative_completed_symbols"] == 50
        assert result["remaining_symbols"] == 0
        assert result["end_to_end_completion_pct"] == 100.0
        assert result["committed_run_count"] == 2
        assert result["attempt_run_count"] == 3
        assert [
            item["run_id"]
            for item in result["committed_runs"]
        ] == [root_id, child_id]
        assert [
            item["run_id"]
            for item in result["attempt_runs"]
        ] == [root_id, child_id, replay_id]
    finally:
        audit_db.close()
        continuation_db.close()



def test_lineage_integrity_detects_consumed_child_without_audit():
    root = _audit(
        "root",
        outcome="partial",
        requested=50,
        completed=25,
        processed=25,
        root="root",
        audit_id=1,
        sla_met=False,
    )
    service = ScanLineageService(
        FakeAuditLineageService([root]),
        FakeContinuationLineageService(
            [
                _continuation(
                    parent="root",
                    root="root",
                    generation=1,
                    status="consumed",
                    symbols=[f"SYM{i}" for i in range(25)],
                    child="missing-child",
                )
            ]
        ),
    )

    result = service.rollup("root")
    integrity = result["integrity"]

    assert integrity["status"] == "unhealthy"
    assert integrity["valid"] is False
    assert integrity["error_count"] >= 1
    assert any(
        item["code"] == "CONSUMED_CHILD_AUDIT_MISSING"
        for item in integrity["issues"]
    )


def test_lineage_integrity_detects_deferred_symbol_mismatch():
    root = _audit(
        "root",
        outcome="partial",
        requested=4,
        completed=2,
        processed=2,
        root="root",
        audit_id=1,
        sla_met=False,
    )
    root["metadata"]["deferred_symbols"] = ["CCC", "DDD"]

    service = ScanLineageService(
        FakeAuditLineageService([root]),
        FakeContinuationLineageService(
            [
                _continuation(
                    parent="root",
                    root="root",
                    generation=1,
                    status="pending",
                    symbols=["CCC", "EEE"],
                    attempts=0,
                )
            ]
        ),
    )

    integrity = service.rollup("root")["integrity"]

    assert integrity["status"] == "unhealthy"
    assert any(
        item["code"]
        == "CONTINUATION_DEFERRED_SYMBOL_MISMATCH"
        for item in integrity["issues"]
    )


def test_lineage_integrity_detects_multiple_executable_continuations():
    root = _audit(
        "root",
        outcome="partial",
        requested=50,
        completed=25,
        processed=25,
        root="root",
        audit_id=1,
        sla_met=False,
    )
    child = _audit(
        "child",
        outcome="partial",
        requested=25,
        completed=12,
        processed=12,
        root="root",
        audit_id=2,
        parent="root",
        generation=1,
        sla_met=False,
    )

    service = ScanLineageService(
        FakeAuditLineageService([root, child]),
        FakeContinuationLineageService(
            [
                _continuation(
                    parent="root",
                    root="root",
                    generation=1,
                    status="pending",
                    symbols=["AAA"],
                    attempts=0,
                ),
                _continuation(
                    parent="child",
                    root="root",
                    generation=2,
                    status="active",
                    symbols=["BBB"],
                    child="active-child",
                    attempts=1,
                ),
            ]
        ),
    )

    integrity = service.rollup("root")["integrity"]

    assert integrity["status"] == "unhealthy"
    assert any(
        item["code"] == "MULTIPLE_EXECUTABLE_CONTINUATIONS"
        for item in integrity["issues"]
    )


def test_cleanup_removed_consumed_record_keeps_committed_history():
    root = _audit(
        "root",
        outcome="partial",
        requested=50,
        completed=25,
        processed=25,
        root="root",
        audit_id=1,
        sla_met=False,
    )
    child = _audit(
        "child",
        outcome="completed",
        requested=25,
        completed=25,
        processed=25,
        root="root",
        audit_id=2,
        parent="root",
        generation=1,
        sla_met=True,
    )

    result = ScanLineageService(
        FakeAuditLineageService([root, child]),
        FakeContinuationLineageService([]),
    ).rollup("root")

    assert result["status"] == "completed"
    assert result["cumulative_completed_symbols"] == 50
    assert result["remaining_symbols"] == 0
    assert result["committed_run_count"] == 2
    assert result["integrity_status"] == "warning"
    assert result["integrity"]["valid"] is True
    assert any(
        item["code"] == "CONTINUATION_RECORD_ABSENT"
        for item in result["integrity"]["issues"]
    )


def test_lineage_integrity_endpoint_returns_diagnostics():
    root = _audit(
        "root",
        outcome="partial",
        requested=50,
        completed=25,
        processed=25,
        root="root",
        audit_id=1,
        sla_met=False,
    )
    audit = FakeAuditLineageService([root])
    continuation = FakeContinuationLineageService(
        [
            _continuation(
                parent="root",
                root="root",
                generation=1,
                status="pending",
                symbols=[f"SYM{i}" for i in range(25)],
                attempts=0,
            )
        ]
    )

    class Factory:
        def scan_run_audit_service(self):
            return audit

        def scan_continuation_service(self):
            return continuation

    response = TestClient(create_app(Factory())).get(
        "/observability/scan-lineages/root/integrity"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requested_run_id"] == "root"
    assert body["lineage_root_run_id"] == "root"
    assert body["lineage_status"] == "resumable"
    assert body["integrity"]["status"] == "healthy"
    assert body["integrity"]["issue_count"] == 0
