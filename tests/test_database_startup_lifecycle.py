from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


def test_app_lifespan_runs_database_initializer():
    calls = []

    def initializer():
        calls.append(True)
        return {"status": "initialized", "migrations": 12}

    app = create_app(database_initializer=initializer)

    with TestClient(app):
        assert app.state.database["status"] == "initialized"

    assert calls == [True]


def test_database_initializer_failure_prevents_ready_startup():
    def initializer():
        raise RuntimeError("database unavailable")

    app = create_app(database_initializer=initializer)

    try:
        with TestClient(app):
            pass
    except RuntimeError as exc:
        assert str(exc) == "database unavailable"
    else:
        raise AssertionError("startup should fail when database initialization fails")
