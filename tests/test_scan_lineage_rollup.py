from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
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
            "lineage_root_run_id": root,
            "parent_run_id": parent,
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
    expires_at="2026-10-14T12:00:00+00:00",
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
