"""Exercise the supported in-process HTTP client and ASGI lifecycle together."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_http_client_runs_requests_inside_the_application_lifespan():
    events = []

    @asynccontextmanager
    async def lifespan(app):
        app.state.ready = True
        events.append("started")
        yield
        events.append("stopped")

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"ready": app.state.ready}

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"ready": True}
        assert events == ["started"]

    assert events == ["started", "stopped"]
