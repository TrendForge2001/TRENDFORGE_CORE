"""Unexpected API failures are safe in responses and application logs."""
from __future__ import annotations

import logging
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
import requests

from api.app import create_app
from api.scanner_error_boundary import install_api_error_boundary

SECRET = "SENTINEL_SECRET_DO_NOT_EXPOSE"


@pytest.mark.parametrize("failure", ["uncaught", "http"])
def test_unexpected_errors_hide_details_and_keep_useful_reference(caplog, failure):
    app = create_app(SimpleNamespace())

    @app.get("/test-failure/{symbol}")
    def broken(symbol: str):
        if failure == "http":
            raise HTTPException(503, detail={"provider_error": SECRET})
        raise RuntimeError(SECRET)

    with caplog.at_level(logging.ERROR):
        response = TestClient(app).get(f"/test-failure/{SECRET}?token={SECRET}")

    assert response.status_code == (503 if failure == "http" else 500)
    body = response.json()
    assert body["detail"] == "Service temporarily unavailable"
    reference = body["reference"]
    assert len(reference) == 12
    assert response.headers["X-Error-Reference"] == reference
    assert SECRET not in response.text
    assert SECRET not in caplog.text
    assert reference in caplog.text
    assert "/test-failure/{symbol}" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_safe_errors_preserve_intentional_validation_and_auth_headers():
    app = create_app(SimpleNamespace())

    @app.get("/test-unauthorized")
    def unauthorized():
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Bearer"})

    client = TestClient(app)
    invalid = client.post("/scan", json={"symbols": []})
    assert invalid.status_code == 422
    assert isinstance(invalid.json()["detail"], list)
    assert "reference" not in invalid.json()
    unauthorized_response = client.get("/test-unauthorized")
    assert unauthorized_response.status_code == 401
    assert unauthorized_response.json() == {"detail": "Sign in required"}
    assert unauthorized_response.headers["WWW-Authenticate"] == "Bearer"
    assert client.get("/scan/%20").json() == {"detail": "Symbol is required"}


@pytest.mark.parametrize("method,path,kwargs", [
    ("get", "/scan/TCS", {}),
    ("post", "/scan", {"json": {"symbols": ["TCS"]}}),
    ("get", "/workspace/stock/TCS", {}),
    ("get", "/health", {}),
])
def test_provider_timeout_has_bounded_safe_failure(caplog, method, path, kwargs):
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(1)
        raise requests.Timeout(f"https://provider.invalid?token={SECRET}")

    provider = SimpleNamespace(safe_quote=unavailable)
    factory = SimpleNamespace(
        health=unavailable,
        scanner_service=lambda: SimpleNamespace(scan=unavailable, scan_many=unavailable),
        providers=SimpleNamespace(quote=lambda: provider),
    )
    client = TestClient(create_app(factory))
    with caplog.at_level(logging.ERROR):
        response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 503
    assert response.json()["error_code"] == "SERVICE_UNAVAILABLE"
    assert len(calls) == 1  # No retries or worker scheduling at the API boundary.
    assert SECRET not in response.text
    assert SECRET not in caplog.text


def test_factory_boundary_installation_is_idempotent():
    app = create_app(SimpleNamespace())
    count = len(app.user_middleware)
    install_api_error_boundary(app)
    assert len(app.user_middleware) == count


def test_workspace_provider_value_error_is_not_a_client_validation_message(caplog):
    def invalid_response(*args, **kwargs):
        raise ValueError(SECRET)

    factory = SimpleNamespace(providers=SimpleNamespace(
        quote=lambda: SimpleNamespace(safe_quote=invalid_response),
    ))
    with caplog.at_level(logging.ERROR):
        response = TestClient(create_app(factory)).get("/workspace/stock/TCS")
    assert response.status_code == 503
    assert SECRET not in response.text
    assert SECRET not in caplog.text


@pytest.mark.parametrize("path", [
    "/workspace/stock/%20", "/workspace/stock/TCS?period=invalid",
    "/workspace/stock/TCS?period=99999999d",
])
def test_workspace_validates_inputs_before_provider_work(path):
    def unexpected_provider_call():
        pytest.fail("Invalid workspace input must not create a provider")

    factory = SimpleNamespace(providers=SimpleNamespace(quote=unexpected_provider_call))
    assert TestClient(create_app(factory)).get(path).status_code == 422
