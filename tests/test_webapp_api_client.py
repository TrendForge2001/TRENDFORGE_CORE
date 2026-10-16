from __future__ import annotations

import pytest

from webapp.api_client import ApiError, TrendForgeApi


class FakeResponse:
    def __init__(
        self,
        *,
        ok=True,
        status_code=200,
        payload=None,
        text="",
        reason="OK",
        url="https://example.test/health",
    ):
        self.ok = ok
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.text = text
        self.reason = reason
        self.url = url
        self.content = b"content"

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_client_normalizes_base_url_and_adds_admin_header():
    session = FakeSession(
        FakeResponse(payload={"status": "ok"})
    )
    client = TrendForgeApi(
        "https://example.test/",
        "secret-key",
        session=session,
    )

    result = client.get_json("/health")

    assert result == {"status": "ok"}
    call = session.calls[0]
    assert call["url"] == "https://example.test/health"
    assert (
        call["headers"]["X-TrendForge-Admin-Key"]
        == "secret-key"
    )


def test_client_accepts_host_without_scheme():
    client = TrendForgeApi(
        "localhost:8000",
        session=FakeSession(FakeResponse(payload={})),
    )

    assert client.base_url == "http://localhost:8000"


def test_client_surfaces_structured_backend_error():
    session = FakeSession(
        FakeResponse(
            ok=False,
            status_code=409,
            reason="Conflict",
            payload={
                "detail": {
                    "message": "Another scan is already running",
                    "run_id": "run-1",
                }
            },
        )
    )
    client = TrendForgeApi(
        "https://example.test",
        session=session,
    )

    with pytest.raises(ApiError) as captured:
        client.post_json(
            "/scan/universe/nifty500",
            {"limit": 25},
        )

    assert captured.value.status_code == 409
    assert (
        captured.value.message
        == "Another scan is already running"
    )
    assert captured.value.detail["run_id"] == "run-1"


def test_client_rejects_empty_api_url():
    with pytest.raises(ValueError, match="API URL"):
        TrendForgeApi("")


def test_client_delete_json_uses_delete_method():
    session = FakeSession(
        FakeResponse(payload={"status": "removed"})
    )
    client = TrendForgeApi(
        "https://example.test",
        "secret-key",
        session=session,
    )

    result = client.delete_json(
        "/watchlists/Swing/symbols/TCS"
    )

    assert result["status"] == "removed"
    assert session.calls[0]["method"] == "DELETE"
    assert (
        session.calls[0]["url"]
        == "https://example.test/watchlists/Swing/symbols/TCS"
    )
