"""Owner HTTP and WebSocket boundary, expiry, CSRF and API privacy."""

import re

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.production_runtime import secure_application
from core.owner_access import (
    COOKIE,
    SESSION_SECONDS,
    OwnerAccessMiddleware,
    issue_token,
    revoke_owner_token,
    valid_token,
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_OWNER_SIGNING_SECRET", "s" * 40)
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "owner-synthetic-key-with-32-characters")
    monkeypatch.delenv("RENDER", raising=False)
    app = FastAPI()

    @app.get("/app/reports")
    def private():
        return {"owner": "synthetic-private-value"}

    @app.websocket("/app/_stcore/stream")
    async def socket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("private")
        await websocket.close()

    app.add_middleware(OwnerAccessMiddleware)
    return TestClient(app)


def csrf(response):
    return re.search('name="csrf" value="([^"]+)"', response.text).group(1)


def login(client, **extra):
    response = client.get("/owner/mobile?next=/app/reports")
    return client.post(
        "/owner/mobile",
        data={
            "csrf": csrf(response),
            "next": "/app/reports",
            "access_key": "owner-synthetic-key-with-32-characters",
            **extra,
        },
        follow_redirects=False,
    )


def test_both_device_links_lock_ui_and_do_not_reveal_data(client):
    response = client.get("/app/reports")
    assert response.status_code == 200
    assert "synthetic-private-value" not in response.text
    assert "Webapp access key" in response.text
    assert "no-store" in response.headers["cache-control"]
    for device in ("mobile", "laptop"):
        response = client.get("/owner/" + device)
        assert response.status_code == 200
        assert 'type="password"' in response.text
        assert "noindex" in response.headers["x-robots-tag"]
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_login_preserves_deep_link_and_sets_http_only_cookie(client):
    response = login(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/app/reports"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert valid_token(client.cookies.get(COOKIE))
    response = client.get("/app/reports")
    assert response.json()["owner"] == "synthetic-private-value"
    assert "no-store" in response.headers["cache-control"]
    client.get("/owner/logout")
    assert "synthetic-private-value" not in client.get("/app/reports").text


def test_csrf_wrong_password_rate_limit_and_redirects(client):
    assert (
        client.post(
            "/owner/laptop", data={"access_key": "owner-synthetic-key-with-32-characters"}
        ).status_code
        == 403
    )
    assert login(client, access_key="wrong").status_code == 401
    assert not client.cookies.get(COOKIE)
    assert login(client, next="https://attacker.example").headers["location"] == "/app/"
    for _ in range(20):
        assert login(client, access_key="wrong").status_code == 401
    assert login(client).status_code == 429


def test_signed_tokens_expire_and_key_rotation_revokes(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_OWNER_SIGNING_SECRET", "s" * 40)
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "owner-synthetic-key-with-32-characters")
    token = issue_token("session", now=1000)
    assert valid_token(token, now=1001)
    assert not valid_token(token, now=999)
    assert not valid_token(token, now=1000 + SESSION_SECONDS)
    assert not valid_token(token + "tampered", now=1001)
    assert not valid_token(token, "login", now=1001)
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "rotated-owner-key-with-32-characters")
    assert not valid_token(token, now=1001)


def test_logout_revokes_token_and_cross_origin_login_is_denied(client):
    login(client)
    token = client.cookies.get(COOKIE)
    assert valid_token(token)
    client.get("/owner/logout")
    assert not valid_token(token)
    response = client.get("/owner/mobile")
    denied = client.post(
        "/owner/mobile",
        data={"csrf": csrf(response), "access_key": "owner-synthetic-key-with-32-characters"},
        headers={"Origin": "https://another.example"},
    )
    assert denied.status_code == 403
    revoke_owner_token("malformed-token")
    assert not valid_token("malformed-token")


def test_websocket_fails_closed_before_accept(client):
    with (
        pytest.raises(WebSocketDisconnect) as denied,
        client.websocket_connect("/app/_stcore/stream"),
    ):
        pytest.fail("Anonymous WebSocket was accepted")
    assert denied.value.code == 4401
    login(client)
    with client.websocket_connect("/app/_stcore/stream") as socket:
        assert socket.receive_text() == "private"


def test_https_cookie_and_missing_configuration(client, monkeypatch):
    with TestClient(client.app, base_url="https://testserver") as https:
        response = login(https)
        assert "Secure" in response.headers["set-cookie"]
    monkeypatch.delenv("TRENDFORGE_WEBAPP_ACCESS_KEY")
    assert client.get("/owner/laptop").status_code == 503


def test_all_business_reads_and_posts_require_admin_key(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "a" * 40)
    app = FastAPI()

    @app.api_route("/private-data", methods=["GET", "HEAD", "POST"])
    def data():
        return {"private": True}

    @app.get("/livez")
    def health():
        return {"status": "ok"}

    secure_application(app)
    client = TestClient(app)
    for method in ("GET", "HEAD", "POST"):
        assert client.request(method, "/private-data").status_code == 401
        response = client.request(
            method, "/private-data", headers={"X-TrendForge-Admin-Key": "a" * 40}
        )
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
    assert client.get("/livez").status_code == 200


def test_public_health_failure_does_not_leak_private_error():
    from api.app import create_app

    class Factory:
        def health(self):
            raise RuntimeError("synthetic-private-error-must-stay-hidden")

    client = TestClient(secure_application(create_app(Factory())))
    response = client.get("/health")
    assert response.status_code == 503
    assert "synthetic-private-error" not in response.text


def test_https_owner_origin_survives_tls_termination(client):
    from core.owner_access import CSRF_COOKIE

    # Render terminates TLS before the internal ASGI HTTP connection. The
    # browser's Origin and Secure cookie still describe the public HTTPS site.
    proxy = TestClient(client.app, base_url="http://trendforge.example")
    token = csrf(proxy.get("/owner/mobile"))
    response = proxy.post(
        "/owner/mobile",
        data={"csrf": token, "access_key": "owner-synthetic-key-with-32-characters"},
        headers={
            "Origin": "https://trendforge.example",
            "Cookie": CSRF_COOKIE + "=" + token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Secure" in response.headers["set-cookie"]


@pytest.mark.parametrize("signing", ["", "short", "owner-synthetic-key-with-32-characters"])
def test_owner_requires_independent_signing_secret(client, monkeypatch, signing):
    monkeypatch.setenv("TRENDFORGE_OWNER_SIGNING_SECRET", signing)
    assert client.get("/owner/laptop").status_code == 503


def test_rotating_signing_key_invalidates_session(client, monkeypatch):
    login(client)
    token = client.cookies.get(COOKIE)
    monkeypatch.setenv("TRENDFORGE_OWNER_SIGNING_SECRET", "different-signing-secret" * 2)
    assert not valid_token(token)
