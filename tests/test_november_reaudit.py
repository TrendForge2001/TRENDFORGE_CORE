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


def test_short_portal_passwords_work_and_empty_or_reused_passwords_fail(monkeypatch):
    values = {
        "WEBAPP_ACCESS_KEY": "a",
        "EXCEL_PASSWORD": "e",
        "KITE_WINDOW_PASSWORD": "k",
    }
    for name, value in values.items():
        monkeypatch.setenv(f"TRENDFORGE_{name}", value)
    report_access.validate_portal_secrets()
    assert report_access.password("excel") == values["EXCEL_PASSWORD"]
    assert report_access.kite_unlocked(
        report_access.kite_token(values["KITE_WINDOW_PASSWORD"])
    )
    session = owner_access.issue_token("session")
    monkeypatch.setattr(owner_access, "_SESSION_EPOCH", b"new process")
    assert not owner_access.valid_token(session)
    for invalid in ("  ", values["WEBAPP_ACCESS_KEY"]):
        monkeypatch.setenv("TRENDFORGE_EXCEL_PASSWORD", invalid)
        with pytest.raises(ValueError, match="distinct"):
            report_access.validate_portal_secrets()


def test_shared_paper_host_allows_research_unless_reserved(monkeypatch):
    from services.cloud_workload_gate import CloudWorkloadBusy, research_admission

    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TRENDFORGE_CLOUD_PAPER_EXECUTION", "true")
    monkeypatch.delenv("TRENDFORGE_RESEARCH_EXECUTION", raising=False)

    @research_admission
    def submit(manager):
        return "accepted"

    assert submit(None) == "accepted"
    monkeypatch.setenv("TRENDFORGE_RESEARCH_EXECUTION", "disabled")

    with pytest.raises(CloudWorkloadBusy, match="reserved for paper"):
        submit(None)
