from pathlib import Path


def test_render_manifest_points_to_canonical_asgi_entrypoint():
    manifest = (Path(__file__).parents[1] / "render.yaml").read_text(encoding="utf-8")
    assert "startCommand: uvicorn start:app --host 0.0.0.0 --port $PORT" in manifest
    assert "healthCheckPath: /health" in manifest


def test_api_app_exposes_asgi_application():
    from api.app import app
    assert getattr(app, "title", "") == "TrendForge Core API"
