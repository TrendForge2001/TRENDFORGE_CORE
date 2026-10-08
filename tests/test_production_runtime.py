from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from api.production_runtime import production_runtime_enabled, secure_application


class Manager:
    def upsert(self, symbol, values, *, source, as_of):
        return {"symbol": symbol.upper(), "fundamentals": values}


class Factory:
    def fundamental_manager(self):
        return Manager()

    def fundamental_completion_service(self):
        raise AssertionError("not used")

    def scanner_service(self):
        raise AssertionError("not used")

    def import_fundamentals_if_configured(self):
        return {"status": "not_configured"}


def _app(monkeypatch):
    monkeypatch.setattr(
        "api.production_runtime.storage_health",
        lambda: {"verified_persistent": True, "status": "persistent"},
    )
    return secure_application(
        create_app(
            Factory(),
            database_initializer=lambda: {"status": "initialized"},
        )
    )


def test_render_automatically_enables_production_runtime():
    assert production_runtime_enabled({"RENDER": "true"}) is True
    assert production_runtime_enabled({"RENDER": "false"}) is False
    assert production_runtime_enabled({}) is False


def test_explicit_production_runtime_override_is_supported():
    assert production_runtime_enabled(
        {
            "RENDER": "false",
            "TRENDFORGE_PRODUCTION_RUNTIME": "true",
        }
    ) is True


def test_production_mutations_fail_closed_without_admin_key(monkeypatch):
    monkeypatch.delenv("TRENDFORGE_ADMIN_API_KEY", raising=False)
    app = _app(monkeypatch)
    response = TestClient(app).put(
        "/fundamentals/ABC",
        json={"roe": 20.0},
    )
    assert response.status_code == 503


def test_production_mutations_require_matching_admin_key(monkeypatch):
    key = "k" * 40
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", key)
    app = _app(monkeypatch)
    denied = TestClient(app).put(
        "/fundamentals/ABC",
        json={"roe": 20.0},
        headers={"X-TrendForge-Admin-Key": "wrong"},
    )
    assert denied.status_code == 401

    allowed = TestClient(app).put(
        "/fundamentals/ABC",
        json={"roe": 20.0},
        headers={"X-TrendForge-Admin-Key": key},
    )
    assert allowed.status_code == 200


def test_production_blocks_admin_writes_on_ephemeral_storage(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "z" * 40)
    app = secure_application(
        create_app(
            Factory(),
            database_initializer=lambda: {"status": "initialized"},
        )
    )
    monkeypatch.setattr(
        "api.production_runtime.storage_health",
        lambda: {
            "verified_persistent": False,
            "status": "ephemeral_or_unverified",
        },
    )
    response = TestClient(app).put(
        "/fundamentals/ABC",
        json={"roe": 20.0},
        headers={"X-TrendForge-Admin-Key": "z" * 40},
    )
    assert response.status_code == 503
    assert "not verified persistent" in response.json()["detail"]


def test_secure_lifespan_records_bootstrap_status(monkeypatch):
    monkeypatch.setattr(
        "api.production_runtime.run_configured_bootstrap",
        lambda: {"status": "applied", "database_records": 11},
    )
    app = secure_application(
        create_app(
            Factory(),
            database_initializer=lambda: {"status": "initialized"},
        )
    )
    with TestClient(app):
        assert app.state.fundamentals_bootstrap["status"] == "applied"
