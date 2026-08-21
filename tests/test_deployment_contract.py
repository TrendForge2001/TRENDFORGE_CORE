from __future__ import annotations

from pathlib import Path


def test_production_entrypoint_exports_asgi_app():
    from start import app
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)


def test_uvicorn_dependency_is_declared():
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    assert "uvicorn" in requirements.lower()


def test_deployment_does_not_depend_on_legacy_keep_alive():
    source = Path("start.py").read_text(encoding="utf-8")
    assert "keep_alive" not in source


def test_health_route_is_part_of_production_app():
    from start import app
    routes = {route.path for route in app.routes}
    assert "/health" in routes
