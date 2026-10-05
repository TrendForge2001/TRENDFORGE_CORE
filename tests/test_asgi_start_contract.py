from __future__ import annotations

from fastapi import FastAPI

from start import app


def test_start_exports_canonical_fastapi_application():
    assert isinstance(app, FastAPI)
    assert app.title == "TrendForge Core API"


def test_start_exposes_health_and_scan_routes():
    routes = {route.path for route in app.routes}
    assert "/health" in routes
    assert "/scan" in routes
    assert "/scan/{symbol}" in routes
