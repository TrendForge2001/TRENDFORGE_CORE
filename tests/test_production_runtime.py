from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from api.app import create_app
from api.production_runtime import (
    dependency_lock_health,
    production_runtime_enabled,
    secure_application,
    storage_health,
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


def test_production_scan_and_backtest_routes_require_admin_key(monkeypatch):
    monkeypatch.delenv("TRENDFORGE_ADMIN_API_KEY", raising=False)
    app = _app(monkeypatch)
    client = TestClient(app)

    requests = (
        ("POST", "/scan", {"symbols": ["TCS"]}),
        ("POST", "/technical/scan", {"symbols": ["TCS"]}),
        ("POST", "/technical/backtest", {"symbol": "TCS"}),
        ("GET", "/scan/TCS", None),
    )
    for method, path, payload in requests:
        response = client.request(method, path, json=payload)
        assert response.status_code == 503, path


def test_storage_health_requires_declared_active_persistent_mount(monkeypatch, tmp_path):
    database = tmp_path / "trendforge.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.delenv("TRENDFORGE_PERSISTENT_MOUNT", raising=False)

    report = storage_health()

    assert report["verified_persistent"] is False
    assert report["persistent_mount"] is None
    assert report["status"] == "ephemeral_or_unverified"


@pytest.mark.parametrize("mount", ["/", "/tmp", "/var/tmp", "/dev"])
def test_unsuitable_mounts_never_claim_durability(monkeypatch, mount):
    monkeypatch.setenv("DATABASE_PATH", mount.rstrip("/") + "/trendforge.db")
    monkeypatch.setenv("TRENDFORGE_PERSISTENT_MOUNT", mount)
    monkeypatch.setenv("TRENDFORGE_STORAGE_RECOVERY_VERIFIED", "true")
    monkeypatch.setattr("api.production_runtime.os.path.ismount", lambda _: True)
    assert storage_health()["verified_persistent"] is False


def test_mount_requires_explicit_recovery_confirmation(monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", "/var/data/trendforge.db")
    monkeypatch.setenv("TRENDFORGE_PERSISTENT_MOUNT", "/var/data")
    monkeypatch.delenv("TRENDFORGE_STORAGE_RECOVERY_VERIFIED", raising=False)
    monkeypatch.setattr("api.production_runtime.os.path.ismount", lambda _: True)
    assert storage_health()["verified_persistent"] is False
    monkeypatch.setenv("TRENDFORGE_STORAGE_RECOVERY_VERIFIED", "true")
    assert storage_health()["verified_persistent"] is True
    monkeypatch.setenv("DATABASE_PATH", "/var/other/trendforge.db")
    assert storage_health()["verified_persistent"] is False


@pytest.mark.parametrize("path", ["/portfolio", "/pnl", "/performance", "/workspace/paper-portfolio"])
def test_private_portfolio_aliases_deny_unauthenticated_reads(monkeypatch, path):
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "k" * 40)
    client = TestClient(_app(monkeypatch))
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-TrendForge-Admin-Key": "wrong"}).status_code == 401


def test_private_portfolio_correct_key_returns_data(monkeypatch):
    class Paper:
        def snapshot(self):
            return {"positions": [{"symbol": "PRIVATE_FIXTURE"}]}

    class PrivateFactory:
        def paper_trading_service(self):
            return Paper()

    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "k" * 40)
    app = secure_application(create_app(PrivateFactory()))
    client = TestClient(app)
    assert "PRIVATE_FIXTURE" not in client.get("/workspace/paper-portfolio").text
    allowed = client.get("/workspace/paper-portfolio", headers={"X-TrendForge-Admin-Key": "k" * 40})
    assert allowed.status_code == 200
    assert "PRIVATE_FIXTURE" in allowed.text


def test_production_factory_applies_security(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_PRODUCTION_RUNTIME", "true")
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "k" * 40)
    assert TestClient(create_app(Factory())).get("/portfolio").status_code == 401


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
    assert dependencies["missing_count"] == 0
    assert dependencies["mismatched_count"] == 0


def test_production_health_reports_narrow_scheduler_security(
    monkeypatch,
):
    scheduler_key = "s" * 40
    monkeypatch.setenv(
        "TRENDFORGE_SCHEDULER_API_KEY",
        scheduler_key,
    )
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY",
        "a" * 40,
    )
    app = _app(monkeypatch)

    with TestClient(app) as client:
        response = client.get("/production/health")

    assert response.status_code == 200
    security = response.json()["scheduler_security"]
    assert security["status"] == "ready"
    assert security["distinct_from_admin_api_key"] is True
    assert security["scope"] == "operations_external_tick_only"
    assert scheduler_key not in str(response.json())
