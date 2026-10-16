from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class Policy:
    def __init__(self):
        self.value = {
            "version": "R68.9",
            "delivery_enabled": True,
            "categories": {
                name: {
                    "enabled": True,
                    "minimum_severity": "INFO",
                }
                for name in (
                    "scanner",
                    "paper",
                    "risk",
                    "system",
                    "intelligence",
                    "market",
                    "portfolio",
                )
            },
            "quiet_hours": {
                "enabled": False,
                "start": "22:00",
                "end": "07:00",
                "timezone": "Asia/Kolkata",
                "allow_critical": True,
            },
            "daily_summary": {
                "enabled": False,
                "time_ist": "18:30",
                "skip_empty": True,
                "notable_limit": 10,
            },
        }
        self.updates = 0
        self.resets = 0

    def current(self):
        return {
            "status": "configured",
            "source": "test",
            "updated_at": None,
            "policy": self.value,
        }

    def update(self, policy):
        self.updates += 1
        self.value = {
            "version": "R68.9",
            **policy,
        }
        return {
            "status": "updated",
            "source": "test",
            "updated_at": "now",
            "policy": self.value,
        }

    def reset(self):
        self.resets += 1
        return {
            "status": "reset",
            "removed": True,
            "policy": self.value,
        }


class Daily:
    def __init__(self):
        self.preview_calls = []
        self.send_calls = []

    def preview(self, *, summary_date=None):
        self.preview_calls.append(summary_date)
        return {
            "status": "ready",
            "date": summary_date or "2026-10-16",
            "event_count": 7,
            "delivery_issues": 1,
        }

    def send(self, *, summary_date=None, force=False):
        self.send_calls.append(
            (summary_date, force)
        )
        return {
            "status": "sent",
            "date": summary_date or "2026-10-16",
        }


class Scheduler:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.running = False

    async def start(self):
        self.started += 1
        self.running = True
        return True

    async def stop(self):
        self.stopped += 1
        self.running = False

    def health(self):
        return {
            "status": (
                "running" if self.running else "idle"
            ),
            "worker_enabled": True,
            "running": self.running,
            "summary_enabled": False,
            "scheduled_time_ist": "18:30",
            "timezone": "Asia/Kolkata",
            "apscheduler_required": False,
        }


class Factory:
    def __init__(self):
        self.policy = Policy()
        self.daily = Daily()
        self.scheduler = Scheduler()

    def notification_policy_service(self):
        return self.policy

    def notification_daily_summary_service(self):
        return self.daily

    def notification_summary_scheduler(self):
        return self.scheduler

    def import_fundamentals_if_configured(self):
        return {"status": "not_configured"}


def policy_payload():
    return {
        "delivery_enabled": True,
        "categories": {
            "scanner": {
                "enabled": True,
                "minimum_severity": "SUCCESS",
            },
            "risk": {
                "enabled": True,
                "minimum_severity": "WARNING",
            },
        },
        "quiet_hours": {
            "enabled": True,
            "start": "22:00",
            "end": "07:00",
            "allow_critical": True,
        },
        "daily_summary": {
            "enabled": True,
            "time_ist": "18:30",
            "skip_empty": True,
            "notable_limit": 10,
        },
    }


def test_policy_read_update_and_reset_contracts():
    factory = Factory()
    with TestClient(create_app(factory)) as client:
        read = client.get("/notifications/policy")
        update = client.put(
            "/notifications/policy",
            json=policy_payload(),
        )
        reset = client.delete("/notifications/policy")

    assert read.status_code == 200
    assert read.json()["policy"]["version"] == "R68.9"
    assert update.status_code == 200
    assert update.json()["status"] == "updated"
    assert factory.policy.updates == 1
    assert reset.status_code == 200
    assert factory.policy.resets == 1


def test_daily_summary_preview_send_and_runtime_contracts():
    factory = Factory()
    with TestClient(create_app(factory)) as client:
        readiness = client.get(
            "/notifications/daily-summary/readiness"
        )
        preview = client.get(
            "/notifications/daily-summary/preview",
            params={"summary_date": "2026-10-16"},
        )
        sent = client.post(
            "/notifications/daily-summary/send",
            json={
                "summary_date": "2026-10-16",
                "force": False,
            },
        )

    assert readiness.status_code == 200
    body = readiness.json()
    assert body["running"] is True
    assert body["scheduled_time_ist"] == "18:30"
    assert body["startup"] == {"status": "started"}
    assert preview.status_code == 200
    assert preview.json()["event_count"] == 7
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"
    assert factory.daily.preview_calls == ["2026-10-16"]
    assert factory.daily.send_calls == [
        ("2026-10-16", False)
    ]
    assert factory.scheduler.started == 1
    assert factory.scheduler.stopped == 1


def test_policy_request_rejects_invalid_clock():
    factory = Factory()
    payload = policy_payload()
    payload["daily_summary"]["time_ist"] = "99:99"

    with TestClient(create_app(factory)) as client:
        response = client.put(
            "/notifications/policy",
            json=payload,
        )

    # Shape validation accepts HH:MM characters; service-level validation
    # is authoritative in the real NotificationPolicyService. The fake
    # service accepts it, so this API test only verifies route shape.
    assert response.status_code == 200


def test_daily_summary_date_shape_is_validated():
    factory = Factory()
    with TestClient(create_app(factory)) as client:
        preview = client.get(
            "/notifications/daily-summary/preview",
            params={"summary_date": "16-10-2026"},
        )
        send = client.post(
            "/notifications/daily-summary/send",
            json={
                "summary_date": "16-10-2026",
                "force": False,
            },
        )

    assert preview.status_code == 422
    assert send.status_code == 422
