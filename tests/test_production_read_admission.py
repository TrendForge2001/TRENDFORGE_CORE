"""Public diagnostics and cached reads must not grant refresh privileges."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from api.app import create_app
from api.production_runtime import secure_application


ADMIN_KEY = "a" * 40
REFRESH_ROUTES = (
    ("/universe/nifty500", "refresh"),
    ("/fundamentals/readiness", "refresh_universe"),
)


class ReadFactory:
    def __init__(self):
        self.calls = []

    def nifty500_universe(self):
        self.calls.append("universe_factory")
        return self

    def fundamental_coverage_service(self):
        self.calls.append("coverage_factory")
        return self

    def ensure_loaded(self, *, refresh=False):
        self.calls.append(("ensure_loaded", refresh))

    def report(self, *, refresh_universe=False, **kwargs):
        self.calls.append(("report", refresh_universe))
        return {"status": "ready", "cached": not refresh_universe}


def _client(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", ADMIN_KEY)
    factory = ReadFactory()
    app = secure_application(create_app(factory))
    return TestClient(app), factory


@pytest.mark.parametrize("path,flag", REFRESH_ROUTES)
@pytest.mark.parametrize("value", ["true", "TRUE", "1", "on", "yes", "t", "y"])
def test_public_explicit_refresh_cannot_start_provider_work(monkeypatch, path, flag, value):
    client, factory = _client(monkeypatch)

    response = client.get(path, params={flag: value})

    assert response.status_code == 401
    assert factory.calls == []


@pytest.mark.parametrize("path,flag", REFRESH_ROUTES)
def test_refresh_with_wrong_key_cannot_start_provider_work(monkeypatch, path, flag):
    client, factory = _client(monkeypatch)
    response = client.get(
        path, params={flag: "true"}, headers={"X-TrendForge-Admin-Key": "wrong"},
    )
    assert response.status_code == 401
    assert factory.calls == []


@pytest.mark.parametrize("path,flag", REFRESH_ROUTES)
def test_refresh_fails_closed_if_admin_key_not_configured(monkeypatch, path, flag):
    client, factory = _client(monkeypatch)
    monkeypatch.delenv("TRENDFORGE_ADMIN_API_KEY")

    assert client.get(path, params={flag: "true"}).status_code == 503
    assert factory.calls == []


@pytest.mark.parametrize("path,flag", REFRESH_ROUTES)
def test_admin_refresh_still_reaches_provider(monkeypatch, path, flag):
    client, factory = _client(monkeypatch)

    response = client.get(
        path, params={flag: "true"}, headers={"X-TrendForge-Admin-Key": ADMIN_KEY},
    )

    assert response.status_code == 200
    assert ("ensure_loaded", True) in factory.calls or ("report", True) in factory.calls


@pytest.mark.parametrize("path,flag", REFRESH_ROUTES)
@pytest.mark.parametrize("params", [{}, {"value": "false"}, {"value": "0"}])
def test_ordinary_cached_reads_remain_public(monkeypatch, path, flag, params):
    client, factory = _client(monkeypatch)

    response = client.get(path, params={flag: params["value"]} if params else {})

    assert response.status_code == 200
    assert factory.calls
    assert ("ensure_loaded", True) not in factory.calls
    assert ("report", True) not in factory.calls


@pytest.mark.parametrize("path,flag", REFRESH_ROUTES)
def test_repeated_refresh_flags_cannot_bypass_authentication(monkeypatch, path, flag):
    client, factory = _client(monkeypatch)

    response = client.get(path, params=[(flag, "true"), (flag, "false")])

    assert response.status_code == 401
    assert factory.calls == []


@pytest.mark.parametrize("path,flag", REFRESH_ROUTES)
def test_invalid_refresh_boolean_retains_validation_error(monkeypatch, path, flag):
    client, factory = _client(monkeypatch)

    assert client.get(path, params={flag: "invalid"}).status_code == 422
    assert factory.calls == []


def test_public_health_omits_internal_paths_and_bootstrap_errors(monkeypatch):
    secret = "/private/SENTINEL_TOKEN_123"
    sha = "b" * 40
    monkeypatch.setenv("RENDER_GIT_COMMIT", sha)
    monkeypatch.setenv("RENDER_SERVICE_ID", secret)
    monkeypatch.setattr(
        "api.production_runtime.database_health",
        lambda: {"status": "degraded", "exists": True, "path": secret, "error": secret},
    )
    monkeypatch.setattr(
        "api.production_runtime.storage_health",
        lambda: {"status": "ephemeral_or_unverified", "verified_persistent": False,
                 "database_path": secret, "parent": secret, "durability_reason": secret},
    )
    monkeypatch.setattr(
        "api.production_runtime.dependency_lock_health",
        lambda: {"status": "invalid", "file": secret, "invalid_entry": secret,
                 "locked_packages": 1, "missing": [secret], "mismatched": [secret]},
    )
    client, _ = _client(monkeypatch)
    client.app.state.fundamentals_bootstrap = {"status": "failed", "file": secret, "error": secret}

    response = client.get("/production/health")

    assert response.status_code == 200
    assert secret not in response.text
    assert response.json()["deployment"]["render_git_commit"] == sha
    assert response.json()["storage"]["verified_persistent"] is False
    assert response.json()["bootstrap"] == {"status": "failed"}
    assert response.json()["dependencies"]["missing_count"] == 1
    assert response.json()["dependencies"]["mismatched_count"] == 1


def test_detailed_health_requires_matching_admin_key(monkeypatch):
    client, _ = _client(monkeypatch)
    client.app.state.fundamentals_bootstrap = {"status": "failed", "error": "diagnostic_only"}

    assert client.get("/production/health?details=true").status_code == 401
    assert client.get(
        "/production/health?details=true", headers={"X-TrendForge-Admin-Key": "wrong"},
    ).status_code == 401
    allowed = client.get(
        "/production/health?details=true", headers={"X-TrendForge-Admin-Key": ADMIN_KEY},
    )
    assert allowed.status_code == 200
    assert allowed.json()["bootstrap"]["error"] == "diagnostic_only"


def test_core_health_projects_public_status_and_protects_full_report(monkeypatch):
    secret = "INTERNAL_PATH_OR_PROVIDER_SECRET"
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", ADMIN_KEY)
    factory = ReadFactory()
    factory.health = lambda: {
        "status": "degraded", "error": secret,
        "database": {"status": "ready", "path": secret},
        "market_data": {"status": "degraded", "auth_error": secret},
        "universe": {"nifty500": {"status": "configured", "last_error": secret}},
    }
    client = TestClient(secure_application(create_app(factory)))

    public = client.get("/health")
    assert public.status_code == 200
    assert secret not in public.text
    assert public.json()["market_data"]["status"] == "degraded"
    assert public.json()["universe"]["nifty500"]["status"] == "configured"
    assert client.get("/health?details=true").status_code == 401
    assert client.get("/health?details=true", headers={"X-TrendForge-Admin-Key": "wrong"}).status_code == 401
    private = client.get("/health?details=true", headers={"X-TrendForge-Admin-Key": ADMIN_KEY})
    assert private.status_code == 200
    assert private.json()["database"]["path"] == secret

