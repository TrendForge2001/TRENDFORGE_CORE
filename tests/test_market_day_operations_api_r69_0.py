from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class Operations:
    def __init__(self):
        self.updated = 0
        self.reset = 0
        self.run_calls = []

    def session(self):
        return {
            "status": "ready",
            "market_day": True,
            "phase": "market_open_paper_entry",
            "date_ist": "2026-10-16",
        }

    def policy(self):
        return {
            "status": "configured",
            "source": "test",
            "updated_at": None,
            "policy": {
                "version": "R69.0",
                "automation_enabled": False,
                "market_day_only": True,
                "calendar": {
                    "holiday_dates": [],
                    "special_trading_dates": [],
                },
                "market_context_limit": 100,
                "morning": {
                    "enabled": True,
                    "time_ist": "08:45",
                    "grace_minutes": 30,
                    "refresh_market_context": True,
                    "notify_discord": True,
                },
                "eod": {
                    "enabled": True,
                    "time_ist": "15:45",
                    "grace_minutes": 30,
                    "paper_safety_tick": True,
                    "refresh_market_context": True,
                    "portfolio_sync": False,
                    "notify_discord": True,
                },
            },
        }

    def update_policy(self, policy):
        self.updated += 1
        return {
            "status": "updated",
            "policy": {
                "version": "R69.0",
                **policy,
            },
        }

    def reset_policy(self):
        self.reset += 1
        return {
            "status": "reset",
            "removed": True,
            "policy": self.policy()["policy"],
        }

    def control_center(self):
        return {
            "status": "ready",
            "version": "R69.0",
            "session": self.session(),
            "safety": {
                "paper_only": True,
                "broker_orders_allowed": False,
                "automatic_scanner_execution": False,
            },
        }

    def runs(self, *, limit=20):
        return {
            "status": "ready",
            "returned": 1,
            "runs": [
                {
                    "run_id": "run-1",
                    "operation": "morning",
                    "status": "completed",
                }
            ][:limit],
        }

    def run(
        self,
        operation,
        *,
        force=False,
        scheduled=False,
    ):
        if operation not in {"morning", "eod"}:
            raise ValueError("operation must be morning or eod")
        self.run_calls.append(
            (operation, force, scheduled)
        )
        return {
            "status": "completed",
            "operation": operation,
            "forced": force,
            "scheduled": scheduled,
            "broker_orders_allowed": False,
        }


class Scheduler:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.running = False
        self.ticks = 0

    async def start(self):
        self.started += 1
        self.running = True
        return True

    async def stop(self):
        self.stopped += 1
        self.running = False

    def tick(self):
        self.ticks += 1
        return {
            "status": "idle",
            "operations": {},
        }

    def health(self):
        return {
            "status": (
                "running"
                if self.running
                else "idle"
            ),
            "worker_enabled": True,
            "running": self.running,
            "automation_enabled": False,
            "morning_time_ist": "08:45",
            "eod_time_ist": "15:45",
            "timezone": "Asia/Kolkata",
            "apscheduler_required": False,
            "broker_orders_allowed": False,
        }


class Factory:
    def __init__(self):
        self.operations = Operations()
        self.scheduler = Scheduler()

    def market_day_operations_service(self):
        return self.operations

    def market_day_operations_scheduler(self):
        return self.scheduler

    def import_fundamentals_if_configured(self):
        return {"status": "not_configured"}


def payload():
    return {
        "automation_enabled": True,
        "market_day_only": True,
        "calendar": {
            "holiday_dates": ["2026-10-20"],
            "special_trading_dates": [],
        },
        "market_context_limit": 100,
        "morning": {
            "enabled": True,
            "time_ist": "08:45",
            "grace_minutes": 30,
            "refresh_market_context": True,
            "notify_discord": True,
        },
        "eod": {
            "enabled": True,
            "time_ist": "15:45",
            "grace_minutes": 30,
            "paper_safety_tick": True,
            "refresh_market_context": True,
            "portfolio_sync": False,
            "notify_discord": True,
        },
    }


def test_operations_read_contracts_and_lifecycle():
    factory = Factory()

    with TestClient(create_app(factory)) as client:
        readiness = client.get("/operations/readiness")
        session = client.get("/operations/session")
        policy = client.get("/operations/policy")
        control = client.get("/operations/control-center")
        runs = client.get(
            "/operations/runs",
            params={"limit": 10},
        )

        assert readiness.status_code == 200
        assert readiness.json()["running"] is True
        assert readiness.json()["startup"] == {
            "status": "started"
        }
        assert session.json()["market_day"] is True
        assert policy.json()["policy"]["version"] == "R69.0"
        assert control.json()["safety"]["broker_orders_allowed"] is False
        assert runs.json()["returned"] == 1

    assert factory.scheduler.started == 1
    assert factory.scheduler.stopped == 1


def test_operations_policy_update_reset_run_and_tick():
    factory = Factory()

    with TestClient(create_app(factory)) as client:
        updated = client.put(
            "/operations/policy",
            json=payload(),
        )
        morning = client.post(
            "/operations/run/morning",
            json={"force": False},
        )
        eod = client.post(
            "/operations/run/eod",
            json={"force": True},
        )
        tick = client.post(
            "/operations/tick",
            json={},
        )
        reset = client.delete("/operations/policy")

    assert updated.status_code == 200
    assert updated.json()["status"] == "updated"
    assert factory.operations.updated == 1
    assert morning.json()["operation"] == "morning"
    assert eod.json()["forced"] is True
    assert factory.operations.run_calls == [
        ("morning", False, False),
        ("eod", True, False),
    ]
    assert tick.json()["status"] == "idle"
    assert factory.scheduler.ticks == 1
    assert reset.json()["status"] == "reset"
    assert factory.operations.reset == 1


def test_operations_policy_rejects_invalid_clock():
    factory = Factory()
    request = payload()
    request["morning"]["time_ist"] = "29:90"

    with TestClient(create_app(factory)) as client:
        response = client.put(
            "/operations/policy",
            json=request,
        )

    assert response.status_code == 422


def test_operations_policy_rejects_invalid_grace():
    factory = Factory()
    request = payload()
    request["eod"]["grace_minutes"] = 999

    with TestClient(create_app(factory)) as client:
        response = client.put(
            "/operations/policy",
            json=request,
        )

    assert response.status_code == 422


def test_invalid_operation_returns_422():
    with TestClient(create_app(Factory())) as client:
        response = client.post(
            "/operations/run/nope",
            json={"force": False},
        )

    assert response.status_code == 422
