import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.admin_auth import validate_admin_api_key
from api.app import create_app
from core import owner_access, report_access


def test_standalone_api_requires_admin_by_default(monkeypatch):
    monkeypatch.delenv("TRENDFORGE_API_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "a" * 40)
    client = TestClient(create_app(), base_url="https://testserver")
    response = client.get("/health?details=true")
    assert response.status_code == 401
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors" in response.headers["content-security-policy"]
    assert "max-age" in response.headers["strict-transport-security"]
    assert client.get("/health").json() == {"status": "ok"}
    with pytest.raises(HTTPException) as error:
        validate_admin_api_key("é")
    assert error.value.status_code == 401


def test_dedicated_credentials_and_restart(monkeypatch):
    for name, letter in (
        ("WEBAPP_ACCESS_KEY", "a"),
        ("KITE_WINDOW_PASSWORD", "b"),
        ("EXCEL_PASSWORD", "c"),
    ):
        monkeypatch.setenv("TRENDFORGE_" + name, letter * 32)
    report_access.validate_portal_secrets()
    token = owner_access.issue_token("session")
    monkeypatch.setattr(owner_access, "_SESSION_EPOCH", b"next-process")
    assert not owner_access.valid_token(token)
    monkeypatch.setenv("TRENDFORGE_EXCEL_PASSWORD", "a" * 32)
    with pytest.raises(ValueError, match="distinct"):
        report_access.validate_portal_secrets()


def test_kite_rate_limit_expires(monkeypatch):
    from collections import deque

    monkeypatch.setattr(report_access, "_attempts", deque())
    monkeypatch.setattr(report_access.time, "monotonic", lambda: 100)
    monkeypatch.setenv("TRENDFORGE_KITE_WINDOW_PASSWORD", "b" * 32)
    for _ in range(10):
        with pytest.raises(ValueError, match="Incorrect"):
            report_access.kite_token("incorrect")
    with pytest.raises(ValueError, match="Too many"):
        report_access.kite_token("b" * 32)
    monkeypatch.setattr(report_access.time, "monotonic", lambda: 401)
    assert report_access.kite_unlocked(report_access.kite_token("b" * 32))


def test_owner_portal_rejects_short_and_reused_credentials(monkeypatch):
    values = {
        "WEBAPP_ACCESS_KEY": "a" * 40,
        "EXCEL_PASSWORD": "e" * 40,
        "KITE_WINDOW_PASSWORD": "k" * 40,
    }
    for name, value in values.items():
        monkeypatch.setenv(f"TRENDFORGE_{name}", value)
    report_access.validate_portal_secrets()
    session = owner_access.issue_token("session")
    monkeypatch.setattr(owner_access, "_SESSION_EPOCH", b"new process")
    assert not owner_access.valid_token(session)
    for invalid in ("short", values["WEBAPP_ACCESS_KEY"]):
        monkeypatch.setenv("TRENDFORGE_EXCEL_PASSWORD", invalid)
        with pytest.raises(ValueError, match="distinct"):
            report_access.validate_portal_secrets()


def test_paper_host_refuses_research_before_starting_workers(monkeypatch):
    from services.cloud_workload_gate import CloudWorkloadBusy, research_admission

    monkeypatch.setenv("TRENDFORGE_CLOUD_PAPER_EXECUTION", "true")
    monkeypatch.delenv("TRENDFORGE_RESEARCH_EXECUTION", raising=False)

    @research_admission
    def submit(manager):
        pytest.fail("Paper host started research")

    with pytest.raises(CloudWorkloadBusy, match="reserved for paper"):
        submit(None)
