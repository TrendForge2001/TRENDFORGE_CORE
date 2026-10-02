from __future__ import annotations

import importlib


def test_production_start_module_exports_asgi_app():
    module = importlib.import_module("start")

    assert module.app is not None
    assert module.app.title == "TrendForge Core API"


def test_start_module_does_not_require_uvicorn_to_import_app():
    module = importlib.import_module("start")

    assert hasattr(module, "app")
