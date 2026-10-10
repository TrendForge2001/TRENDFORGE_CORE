from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from api.production_runtime import (
    dependency_lock_health,
    production_runtime_enabled,
    secure_application,
)


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


def test_production_health_reports_python_version(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
    app = _app(monkeypatch)

    with TestClient(app) as client:
        response = client.get("/production/health")

    assert response.status_code == 200
    deployment = response.json()["deployment"]
    assert deployment["render_git_commit"] == "abc123"
    assert deployment["python_version"]
    assert deployment["python_version"].startswith("3.")


def test_dependency_lock_health_verifies_installed_versions(
    monkeypatch,
    tmp_path,
):
    lock = tmp_path / "requirements-production.lock"
    lock.write_text(
        "alpha==1.2.3\nbeta==4.5.6\n",
        encoding="utf-8",
    )

    versions = {
        "alpha": "1.2.3",
        "beta": "4.5.6",
    }
    monkeypatch.setattr(
        "api.production_runtime.metadata.version",
        lambda name: versions[name],
    )

    health = dependency_lock_health(lock)

    assert health["status"] == "runtime_verified"
    assert health["locked_packages"] == 2
    assert health["missing"] == []
    assert health["mismatched"] == []
    assert len(health["file_sha256"]) == 64


def test_dependency_lock_health_detects_version_drift(
    monkeypatch,
    tmp_path,
):
    lock = tmp_path / "requirements-production.lock"
    lock.write_text("alpha==1.2.3\n", encoding="utf-8")

    monkeypatch.setattr(
        "api.production_runtime.metadata.version",
        lambda name: "9.9.9",
    )

    health = dependency_lock_health(lock)

    assert health["status"] == "degraded"
    assert health["missing"] == []
    assert health["mismatched"] == [
        {
            "package": "alpha",
            "expected": "1.2.3",
            "installed": "9.9.9",
        }
    ]


def test_production_health_includes_dependency_lock_status(monkeypatch):
    monkeypatch.setattr(
        "api.production_runtime.dependency_lock_health",
        lambda: {
            "status": "runtime_verified",
            "locked_packages": 62,
            "missing": [],
            "mismatched": [],
            "file_sha256": "a" * 64,
        },
    )
    app = _app(monkeypatch)

    with TestClient(app) as client:
        response = client.get("/production/health")

    assert response.status_code == 200
    dependencies = response.json()["dependencies"]
    assert dependencies["status"] == "runtime_verified"
    assert dependencies["locked_packages"] == 62
    assert dependencies["missing"] == []
    assert dependencies["mismatched"] == []
