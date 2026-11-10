"""The egress diagnostic is private, read-only and does not construct a broker."""

import secrets

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.trading_workspace_router import attach_trading_workspace_routes


def test_network_probe_requires_admin_and_does_not_initialize_a_broker(monkeypatch):
    key = secrets.token_hex(32)
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", key)
    calls = []

    def report(*, probe=False):
        calls.append(probe)
        return {
            "status": "fixed_egress_not_configured",
            "orders_submitted": 0,
            "broker_orders_allowed": False,
        }

    def forbidden():
        raise AssertionError("Network diagnostics must not construct a broker")

    monkeypatch.setattr(
        "services.kite_network_readiness.kite_network_readiness", report
    )
    app = FastAPI()
    attach_trading_workspace_routes(
        app,
        intelligence_getter=forbidden,
        paper_getter=forbidden,
        provider_factory_getter=forbidden,
    )
    client = TestClient(app)
    path = "/workspace/kite-network-readiness"
    assert client.get(path, params={"probe": True}).status_code == 401
    assert calls == []
    response = client.get(path, headers={"X-TrendForge-Admin-Key": key})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["orders_submitted"] == 0
    response = client.get(
        path,
        params={"probe": True},
        headers={"X-TrendForge-Admin-Key": key},
    )
    assert response.status_code == 200
    assert calls == [False, True]
