from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_render_uses_canonical_asgi_entrypoint_and_health_check():
    text = _text("render.yaml")

    assert "runtime: python" in text
    assert "buildCommand: python -m pip install -r requirements-production.lock" in text
    assert "startCommand: uvicorn start:app --host 0.0.0.0 --port $PORT" in text
    assert "healthCheckPath: /health" in text


def test_production_entrypoint_and_render_command_use_same_app():
    start = _text("start.py")
    render = _text("render.yaml")

    assert "from api.app import app" in start
    assert "uvicorn start:app" in render


def test_runtime_dependencies_cover_asgi_and_application_imports():
    requirements = _text("requirements.txt")

    for package in ("fastapi", "uvicorn[standard]", "httpx", "pandas", "numpy"):
        assert package in requirements


def test_runtime_dependency_file_does_not_reintroduce_pandas_ta():
    requirements = _text("requirements.txt").lower()

    assert "pandas-ta" not in requirements
    assert "pandas_ta" not in requirements


def test_render_does_not_enable_live_trading_by_default():
    text = _text("render.yaml").lower()

    assert "live_trading=true" not in text
    assert "enable_live_trading=true" not in text
