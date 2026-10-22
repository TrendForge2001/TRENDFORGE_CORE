"""R72.6 Kite session endpoint is admin-gated and must never submit orders."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin_auth import require_admin_api_key
from api.trading_workspace_router import attach_trading_workspace_routes


class FakeKite:
    def health(self):
        return {"authenticated": True, "auth_error": "private"}

    def positions(self):
        return {"day": [], "net": [{"tradingsymbol": "SBIN", "quantity": 1}]}

    def holdings(self):
        return [{"tradingsymbol": "TCS", "quantity": 1}]

    def orders(self):
        return [{"order_id": "test", "status": "COMPLETE"}]

    def margins(self):
        return {"equity": {"available": {"cash": 2000}}}

    def place_order(self, **_kwargs):
        raise AssertionError("read-only endpoint must never submit broker orders")


class FakeFactory:
    def _default_kite(self):
        return FakeKite()


def app_with_fake():
    app = FastAPI()
    attach_trading_workspace_routes(
        app, intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        provider_factory=FakeFactory(),
    )
    return app


def test_session_requires_admin_authentication():
    app = app_with_fake()
    # Explicitly deny the dependency without needing a real secret.
    def deny():
        from fastapi import HTTPException
        raise HTTPException(401, detail="unauthorized")
    app.dependency_overrides[require_admin_api_key] = deny
    result = TestClient(app).get("/workspace/kite-session")
    assert result.status_code == 401


def test_broker_session_read_only_with_explicitly_disabled_order_execution():
    app = app_with_fake()
    app.dependency_overrides[require_admin_api_key] = lambda: None
    result = TestClient(app).get("/workspace/kite-session")
    assert result.status_code == 200
    payload = result.json()
    assert payload["authenticated"] is True
    assert payload["read_only"] is True
    assert payload["broker_orders_allowed"] is False
    assert payload["orders"][0]["order_id"] == "test"
    assert payload["holdings"][0]["tradingsymbol"] == "TCS"
    assert "auth_error" not in str(payload)
