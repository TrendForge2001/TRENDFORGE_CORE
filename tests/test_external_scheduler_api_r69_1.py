from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class Operations:
    def __init__(self):
        self.satisfied = False
        self.contract_calls = []

    def external_contract(self, operation):
        self.contract_calls.append(operation)
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
            "now_ist": "2026-10-16T08:45:00+05:30",
            "market_day": True,
            "market_phase": "pre_market",
            "scheduled_time_ist": "08:45",
            "grace_minutes": 30,
            "window_start_ist": (
                "2026-10-16T08:45:00+05:30"
            ),
            "window_end_ist": (
                "2026-10-16T09:15:00+05:30"
            ),
            "successful_run": (
                {
                    "run_id": "run-1",
                    "status": "completed",
                }
                if self.satisfied
                else None
            ),
            "automation_enabled": True,
            "operation_enabled": True,
            "broker_orders_allowed": False,
        }


class Scheduler:
    def __init__(self, operations):
        self.operations = operations
        self.external_flags = []
        self.running = False

    async def start(self):
        self.running = True
        return True

    async def stop(self):
        self.running = False

    def tick(self, *, external=False):
        self.external_flags.append(external)
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

    def health(self):
        return {
            "status": (
                "running"
                if self.running
                else "idle"
            ),
            "worker_enabled": False,
            "running": self.running,
            "automation_enabled": True,
            "morning_time_ist": "08:45",
            "eod_time_ist": "15:45",
            "timezone": "Asia/Kolkata",
            "apscheduler_required": False,
            "broker_orders_allowed": False,
        }


class Factory:
    def __init__(self):
        self.operations = Operations()
        self.scheduler = Scheduler(
            self.operations
        )

    def market_day_operations_service(self):
        return self.operations

    def market_day_operations_scheduler(self):
        return self.scheduler

    def import_fundamentals_if_configured(self):
        return {"status": "not_configured"}


def test_external_scheduler_readiness_does_not_expose_secret(
    monkeypatch,
):
    secret = "s" * 40
    monkeypatch.setenv(
        "TRENDFORGE_SCHEDULER_API_KEY",
        secret,
    )
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY",
        "a" * 40,
    )

    with TestClient(create_app(Factory())) as client:
        response = client.get(
            "/operations/external-scheduler/readiness"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["scope"] == (
        "operations_external_tick_only"
    )
    assert body["broker_orders_allowed"] is False
    assert secret not in str(body)


def test_external_scheduler_status_is_read_only_contract():
    factory = Factory()

    with TestClient(create_app(factory)) as client:
        response = client.get(
            "/operations/external-scheduler/status",
            params={"operation": "morning"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "due"
    assert factory.scheduler.external_flags == []


def test_external_tick_fails_closed_without_scheduler_key(
    monkeypatch,
):
    monkeypatch.delenv(
        "TRENDFORGE_SCHEDULER_API_KEY",
        raising=False,
    )

    with TestClient(create_app(Factory())) as client:
        response = client.post(
            "/operations/external-tick",
            json={"expected_operation": "morning"},
        )

    assert response.status_code == 503


def test_external_tick_rejects_wrong_scheduler_key(
    monkeypatch,
):
    monkeypatch.setenv(
        "TRENDFORGE_SCHEDULER_API_KEY",
        "s" * 40,
    )
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY",
        "a" * 40,
    )

    with TestClient(create_app(Factory())) as client:
        response = client.post(
            "/operations/external-tick",
            json={"expected_operation": "morning"},
            headers={
                "X-TrendForge-Scheduler-Key": "wrong"
            },
        )

    assert response.status_code == 401


def test_external_tick_uses_narrow_key_and_external_mode(
    monkeypatch,
):
    secret = "s" * 40
    monkeypatch.setenv(
        "TRENDFORGE_SCHEDULER_API_KEY",
        secret,
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
                "X-TrendForge-Scheduler-Key": secret
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "satisfied"
    assert body["auth_scope"] == (
        "operations_external_tick_only"
    )
    assert body["before"]["status"] == "due"
    assert body["after"]["status"] == "satisfied"
    assert body["tick"]["trigger_source"] == "external"
    assert body["broker_orders_allowed"] is False
    assert factory.scheduler.external_flags == [True]


def test_external_tick_rejects_admin_key_reuse(
    monkeypatch,
):
    secret = "x" * 40
    monkeypatch.setenv(
        "TRENDFORGE_SCHEDULER_API_KEY",
        secret,
    )
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY",
        secret,
    )

    with TestClient(create_app(Factory())) as client:
        response = client.post(
            "/operations/external-tick",
            json={"expected_operation": "morning"},
            headers={
                "X-TrendForge-Scheduler-Key": secret
            },
        )

    assert response.status_code == 503
    assert "distinct" in response.json()["detail"]


def test_external_tick_validates_expected_operation(
    monkeypatch,
):
    monkeypatch.setenv(
        "TRENDFORGE_SCHEDULER_API_KEY",
        "s" * 40,
    )

    with TestClient(create_app(Factory())) as client:
        response = client.post(
            "/operations/external-tick",
            json={"expected_operation": "nope"},
            headers={
                "X-TrendForge-Scheduler-Key": "s" * 40
            },
        )

    assert response.status_code == 422


def test_external_tick_does_not_accept_broad_admin_key(
    monkeypatch,
):
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

    with TestClient(create_app(Factory())) as client:
        response = client.post(
            "/operations/external-tick",
            json={"expected_operation": "morning"},
            headers={
                "X-TrendForge-Scheduler-Key": admin_key
            },
        )

    assert response.status_code == 401
