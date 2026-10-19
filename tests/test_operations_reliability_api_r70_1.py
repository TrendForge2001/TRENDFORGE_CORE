from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from api.production_runtime import _protected_admin_request


class Reliability:
    def __init__(self):
        self.audit_calls = []
        self.tick_records = []
        self.fail_tick_record = False

    def reliability(self, *, days=30):
        return {
            "status": "ready",
            "version": "R70.1",
            "health": "GREEN",
            "window_days": days,
            "reliability_pct": 100.0,
            "broker_orders_allowed": False,
        }

    def history(self, *, limit=100, operation=None):
        return {
            "status": "ready",
            "returned": 1,
            "operation": operation,
            "events": [
                {
                    "audit_id": "audit-1",
                    "operation": operation or "morning",
                    "audit_status": "healthy",
                }
            ][:limit],
        }

    def audit(
        self,
        operation,
        *,
        trigger_source,
        strict,
        deliver_alerts,
    ):
        self.audit_calls.append(
            (
                operation,
                trigger_source,
                strict,
                deliver_alerts,
            )
        )
        return {
            "status": "healthy",
            "operation": operation,
            "audit": {
                "audit_id": "audit-2",
                "reason": "successful_run_recorded",
            },
            "alert": None,
            "broker_orders_allowed": False,
        }

    def audit_all(
        self,
        *,
        trigger_source,
        strict,
        deliver_alerts,
    ):
        self.audit_calls.append(
            (
                "all",
                trigger_source,
                strict,
                deliver_alerts,
            )
        )
        return {
            "status": "ready",
            "results": {},
            "broker_orders_allowed": False,
        }

    def record_external_tick(
        self,
        *,
        operation,
        before,
        tick,
        after,
    ):
        if self.fail_tick_record:
            raise RuntimeError("audit ledger unavailable")
        self.tick_records.append(operation)
        return {
            "audit_id": "tick-audit",
            "event_type": "external_tick",
        }


class Operations:
    def __init__(self):
        self.satisfied = False

    def external_contract(self, operation):
        return {
            "status": (
                "satisfied"
                if self.satisfied
                else "due"
            ),
            "reason": (
                "successful_run_recorded"
                if self.satisfied
                else "inside_window"
            ),
            "operation": operation,
            "date_ist": "2026-10-16",
            "broker_orders_allowed": False,
        }


class Scheduler:
    async def start(self):
        return False

    async def stop(self):
        return None

    def health(self):
        return {
            "status": "worker_disabled",
            "worker_enabled": False,
        }

    def __init__(self, operations):
        self.operations = operations

    def tick(self, *, external=False):
        self.operations.satisfied = True
        return {
            "status": "active_window",
            "trigger_source": (
                "external"
                if external
                else "internal"
            ),
            "operations": {
                "morning": {
                    "status": "completed",
                }
            },
        }


class Factory:
    def __init__(self):
        self.reliability = Reliability()
        self.operations = Operations()
        self.scheduler = Scheduler(self.operations)

    def operations_reliability_service(self):
        return self.reliability

    def market_day_operations_service(self):
        return self.operations

    def market_day_operations_scheduler(self):
        return self.scheduler

    def import_fundamentals_if_configured(self):
        return {"status": "not_configured"}


def test_reliability_and_history_are_read_only():
    factory = Factory()

    with TestClient(create_app(factory)) as client:
        reliability = client.get(
            "/operations/reliability",
            params={"days": 14},
        )
        history = client.get(
            "/operations/audit",
            params={
                "limit": 25,
                "operation": "morning",
            },
        )

    assert reliability.status_code == 200
    assert reliability.json()["window_days"] == 14
    assert history.status_code == 200
    assert history.json()["operation"] == "morning"


def test_manual_audit_contract():
    factory = Factory()

    with TestClient(create_app(factory)) as client:
        one = client.post(
            "/operations/audit/run",
            json={
                "operation": "morning",
                "deliver_alerts": True,
            },
        )
        all_result = client.post(
            "/operations/audit/run",
            json={
                "operation": None,
                "deliver_alerts": False,
            },
        )

    assert one.status_code == 200
    assert one.json()["status"] == "healthy"
    assert all_result.status_code == 200
    assert factory.reliability.audit_calls == [
        (
            "morning",
            "admin_manual",
            False,
            True,
        ),
        (
            "all",
            "admin_manual",
            False,
            False,
        ),
    ]


def test_external_audit_uses_scheduler_only_key(monkeypatch):
    scheduler_key = "s" * 40
    admin_key = "a" * 40
    monkeypatch.setenv(
        "TRENDFORGE_SCHEDULER_API_KEY",
        scheduler_key,
    )
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY",
        admin_key,
    )
    factory = Factory()

    with TestClient(create_app(factory)) as client:
        denied = client.post(
            "/operations/external-audit",
            json={"expected_operation": "morning"},
            headers={
                "X-TrendForge-Scheduler-Key": admin_key
            },
        )
        allowed = client.post(
            "/operations/external-audit",
            json={"expected_operation": "morning"},
            headers={
                "X-TrendForge-Scheduler-Key": scheduler_key
            },
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["auth_scope"] == "operations_external_tick_only"
    assert body["broker_orders_allowed"] is False
    assert factory.reliability.audit_calls[-1] == (
        "morning",
        "external_post_window",
        True,
        True,
    )


def test_external_tick_records_audit_evidence_best_effort(monkeypatch):
    key = "s" * 40
    monkeypatch.setenv(
        "TRENDFORGE_SCHEDULER_API_KEY",
        key,
    )
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY",
        "a" * 40,
    )
    factory = Factory()

    with TestClient(create_app(factory)) as client:
        response = client.post(
            "/operations/external-tick",
            json={"expected_operation": "morning"},
            headers={
                "X-TrendForge-Scheduler-Key": key
            },
        )

    assert response.status_code == 200
    assert response.json()["audit_record"]["audit_id"] == "tick-audit"
    assert factory.reliability.tick_records == ["morning"]


def test_external_tick_survives_audit_ledger_failure(monkeypatch):
    key = "s" * 40
    monkeypatch.setenv(
        "TRENDFORGE_SCHEDULER_API_KEY",
        key,
    )
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY",
        "a" * 40,
    )
    factory = Factory()
    factory.reliability.fail_tick_record = True

    with TestClient(create_app(factory)) as client:
        response = client.post(
            "/operations/external-tick",
            json={"expected_operation": "morning"},
            headers={
                "X-TrendForge-Scheduler-Key": key
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "satisfied"
    assert response.json()["audit_record"]["status"] == "failed"


def test_security_boundary_keeps_external_audit_out_of_admin_scope():
    assert _protected_admin_request(
        "POST",
        "/operations/audit/run",
    )
    assert not _protected_admin_request(
        "POST",
        "/operations/external-audit",
    )
    assert not _protected_admin_request(
        "GET",
        "/operations/reliability",
    )
    assert not _protected_admin_request(
        "GET",
        "/operations/audit",
    )
