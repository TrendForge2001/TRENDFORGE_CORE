from __future__ import annotations

from fastapi.testclient import TestClient

from api.admin_auth import require_admin_api_key
from api.app import create_app


class FakeMultiStrategy:
    def __init__(self):
        self.calls = []

    def readiness(self):
        return {
            "status": "ready",
            "version": "R72.5.2-v1",
            "data_policy": "kite_only",
            "execution": {
                "paper_execution_allowed": False,
                "broker_orders_allowed": False,
            },
        }

    def status(self):
        return {
            "status": "idle",
            "version": "R72.5.2-v1",
            "busy": False,
            "last_result": None,
        }

    def trigger(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "status": "started",
            "version": "R72.5.2-v1",
            "run_id": kwargs.get("run_id") or "r7252-test",
            "safety": {
                "paper_execution_allowed": False,
                "broker_orders_allowed": False,
            },
        }


class Factory:
    def __init__(self):
        self.multi = FakeMultiStrategy()

    def multi_strategy_scanner_service(self):
        return self.multi


def _client(factory=None):
    app = create_app(factory or Factory())
    app.dependency_overrides[require_admin_api_key] = lambda: True
    return TestClient(app), app


def test_multi_strategy_readiness_and_status_are_read_only():
    client, _ = _client()

    readiness = client.get("/technical/multi-strategy/readiness")
    status = client.get("/technical/multi-strategy/status")

    assert readiness.status_code == 200
    assert readiness.json()["version"] == "R72.5.2-v1"
    assert status.status_code == 200
    assert status.json()["status"] == "idle"


def test_multi_strategy_run_normalizes_universe_and_forwards_request():
    factory = Factory()
    client, _ = _client(factory)

    response = client.post(
        "/technical/multi-strategy/run",
        json={
            "universe": "NIFTY100",
            "mode": "swing",
            "source": "template",
            "top_n": 15,
            "limit": 25,
        },
    )

    assert response.status_code == 200
    call = factory.multi.calls[0]
    assert call["universe"] == "NIFTY 100"
    assert call["mode"] == "swing"
    assert call["source"] == "template"
    assert call["top_n"] == 15
    assert call["limit"] == 25
    assert response.json()["safety"]["paper_execution_allowed"] is False


def test_multi_strategy_request_rejects_bad_mode():
    client, _ = _client()

    response = client.post(
        "/technical/multi-strategy/run",
        json={
            "universe": "NIFTY 100",
            "mode": "weekly",
        },
    )

    assert response.status_code == 422
