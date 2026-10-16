from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from services.notification_center_service import (
    NotificationEventNotFoundError,
)


class FakeNotificationCenter:
    def __init__(self):
        self.routes = []
        self.tests = 0

    def readiness(self):
        return {
            "status": "ready",
            "channel": "discord",
            "persisted_events": 2,
        }

    def summary(self):
        return {
            "status": "ready",
            "total": 2,
            "sent": 1,
            "recorded": 1,
        }

    def events(self, **kwargs):
        return {
            "status": "ready",
            "returned": 1,
            "filters": kwargs,
            "events": [
                {
                    "event_id": "evt-1",
                    "category": "scanner",
                    "status": "sent",
                }
            ],
        }

    def get(self, event_id):
        if event_id == "missing":
            raise NotificationEventNotFoundError(event_id)
        return {
            "event_id": event_id,
            "status": "sent",
        }

    def route_event(self, **kwargs):
        self.routes.append(dict(kwargs))
        return {
            "event_id": "evt-new",
            "status": (
                "sent" if kwargs.get("deliver") else "recorded"
            ),
            **kwargs,
        }

    def test_delivery(self):
        self.tests += 1
        return {
            "event_id": "evt-test",
            "status": "sent",
        }

    def close(self):
        pass


class Factory:
    def __init__(self):
        self.notifications = FakeNotificationCenter()

    def notification_center_service(self):
        return self.notifications


def test_notification_read_contracts():
    client = TestClient(create_app(Factory()))

    readiness = client.get("/notifications/readiness")
    summary = client.get("/notifications/summary")
    events = client.get(
        "/notifications/events",
        params={
            "limit": 20,
            "category": "scanner",
            "status": "sent",
            "symbol": "TCS",
        },
    )
    detail = client.get("/notifications/events/evt-1")

    assert readiness.status_code == 200
    assert readiness.json()["channel"] == "discord"
    assert summary.status_code == 200
    assert events.status_code == 200
    assert events.json()["returned"] == 1
    assert detail.status_code == 200


def test_notification_event_route_contract():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post(
        "/notifications/events",
        json={
            "event_type": "scanner_pick",
            "category": "scanner",
            "severity": "success",
            "title": "TCS",
            "message": "Qualified",
            "symbol": "tcs",
            "source": "scanner",
            "payload": {"score": 95},
            "deliver": False,
        },
    )

    assert response.status_code == 200
    call = factory.notifications.routes[0]
    assert call["severity"] == "SUCCESS"
    assert call["symbol"] == "TCS"
    assert call["deliver"] is False


def test_notification_test_contract():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post("/notifications/test")

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert factory.notifications.tests == 1


def test_notification_missing_event_is_404():
    client = TestClient(create_app(Factory()))

    response = client.get(
        "/notifications/events/missing"
    )

    assert response.status_code == 404
