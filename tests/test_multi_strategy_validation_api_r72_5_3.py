from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.admin_auth import require_admin_api_key
from api.app import create_app
from scanner.multi_strategy_engine import MultiStrategyEngine


class Factory:
    def __init__(self):
        self.scanner = SimpleNamespace(
            market_data=object(),
            indicators=object(),
            strategies=MultiStrategyEngine(),
            universe_provider=object(),
        )

    def multi_strategy_scanner_service(self):
        return self.scanner


def _client():
    app = create_app(Factory())
    app.dependency_overrides[require_admin_api_key] = lambda: True
    return TestClient(app), app


def test_r7253_readiness_is_historical_only_and_manual():
    client, _ = _client()

    response = client.get(
        "/technical/multi-strategy/validation/readiness"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "R72.5.3-v1"
    assert payload["execution"]["automatic_run"] is False
    assert payload["execution"]["paper_execution_enabled"] is False
    assert payload["execution"]["broker_orders_allowed"] is False


def test_r7253_run_endpoint_forwards_normalized_request(
    monkeypatch,
):
    client, _ = _client()
    captured = {}

    def fake_start(app, *, scanner_service, request):
        captured.update(request)
        return {
            "status": "started",
            "run_id": "r7253-test",
        }

    monkeypatch.setattr(
        "services.multi_strategy_validation_runtime.start_validation",
        fake_start,
    )

    response = client.post(
        "/technical/multi-strategy/validation/run",
        json={
            "universes": ["NIFTY100", "NIFTY 200"],
            "modes": ["SWING", "intraday"],
            "source": "template",
            "capital": 100000,
            "chunk_size": 25,
            "limit": 25,
            "force_refresh_universes": False,
            "force": False,
        },
    )

    assert response.status_code == 200
    assert captured["universes"] == [
        "NIFTY 100",
        "NIFTY 200",
    ]
    assert captured["modes"] == ["swing", "intraday"]
    assert captured["source"] == "template"


def test_r7253_request_rejects_invalid_mode():
    client, _ = _client()

    response = client.post(
        "/technical/multi-strategy/validation/run",
        json={
            "universes": ["NIFTY 100"],
            "modes": ["weekly"],
        },
    )

    assert response.status_code == 422
