"""R72.5.8.1 production scanner-read error boundary integration tests."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest

from api.scanner_error_boundary import scanner_read_error_boundary


def _client(path):
    app = FastAPI()

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        return await scanner_read_error_boundary(request, call_next)

    @app.get(path)
    def broken():
        raise RuntimeError("SECRET_TOKEN_MUST_NOT_LEAK")

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("path", [
    "/technical/multi-strategy/results",
    "/technical/multi-strategy/status",
    "/technical/multi-strategy/readiness",
])
def test_scanner_read_error_returns_sanitized_503(path):
    response = _client(path).get(path)
    assert response.status_code == 503
    data = response.json()
    assert data["error_code"] == "SCANNER_READ_UNAVAILABLE"
    assert len(data["reference"]) == 12
    assert "SECRET_TOKEN" not in response.text


def test_unrelated_route_is_not_intercepted():
    response = _client("/unrelated").get("/unrelated")
    assert response.status_code == 500
