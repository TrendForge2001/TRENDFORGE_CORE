"""Production admission blocks entries before work without blocking safety actions."""
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from api.app import create_app
from api.production_runtime import secure_application

KEY = "p" * 40
HEADERS = {"X-TrendForge-Admin-Key": KEY}
ORDER = {"symbol": "TCS", "quantity": 1, "price": 3000}


def client_for(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", KEY)
    monkeypatch.delenv("TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION", raising=False)
    monkeypatch.setattr("core.paper_storage_policy.storage_health", lambda: {"verified_persistent": False})
    calls = []

    def paper():
        calls.append("factory")
        return SimpleNamespace(
            open=lambda order: {"status": "opened"},
            monitor=lambda quotes: {"status": "monitored"},
            health=lambda: {"status": "locked", "broker_orders_allowed": False},
            set_runtime_kill_switch=lambda enabled: {"kill_switch": enabled},
        )

    factory = SimpleNamespace(paper_trading_service=paper)
    return TestClient(secure_application(create_app(factory))), calls


def test_no_key_cannot_reach_paper_factory_or_get_storage_details(monkeypatch):
    client, calls = client_for(monkeypatch)
    response = client.post("/paper/open", json=ORDER)
    assert response.status_code == 401
    assert calls == []
    assert "entry_storage_policy" not in response.json()


def test_storage_block_prevents_authenticated_factory_work(monkeypatch):
    client, calls = client_for(monkeypatch)
    response = client.post("/paper/open", json=ORDER, headers=HEADERS)
    assert response.status_code == 423
    assert response.json()["error_code"] == "PAPER_STORAGE_REQUIRED"
    assert response.json()["entry_storage_policy"]["mode"] == "blocked"
    assert calls == []


@pytest.mark.parametrize("mode", ["durable", "ephemeral_simulation"])
def test_admitted_storage_still_requires_authentication(monkeypatch, mode):
    client, calls = client_for(monkeypatch)
    if mode == "durable":
        monkeypatch.setattr("core.paper_storage_policy.storage_health", lambda: {"verified_persistent": True})
    else:
        monkeypatch.setenv("TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION", "true")
    assert client.post("/paper/open", json=ORDER).status_code == 401
    assert calls == []
    assert client.post("/paper/open", json=ORDER, headers=HEADERS).status_code == 200
    assert calls == ["factory"]


def test_admin_ephemeral_write_override_does_not_unlock_paper(monkeypatch):
    client, calls = client_for(monkeypatch)
    monkeypatch.setenv("TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES", "true")
    assert client.post("/paper/open", json=ORDER, headers=HEADERS).status_code == 423
    assert calls == []


def test_storage_failure_preserves_monitoring_and_both_kill_directions(monkeypatch):
    client, _ = client_for(monkeypatch)

    def unavailable():
        raise RuntimeError("PRIVATE_STORAGE_SENTINEL")

    monkeypatch.setattr("core.paper_storage_policy.storage_health", unavailable)
    blocked = client.post("/paper/open", json=ORDER, headers=HEADERS)
    assert blocked.status_code == 423
    assert "PRIVATE_STORAGE_SENTINEL" not in blocked.text
    assert client.get("/paper/readiness", headers=HEADERS).status_code == 200
    assert client.post("/paper/monitor", json={"quotes": {}}, headers=HEADERS).status_code == 200
    for enabled in (True, False):
        response = client.post("/paper/kill-switch", json={"enabled": enabled}, headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["kill_switch"] is enabled
