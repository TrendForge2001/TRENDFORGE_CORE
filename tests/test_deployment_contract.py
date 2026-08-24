"""Deployment configuration contract tests."""
from pathlib import Path


def test_render_configuration_uses_api_and_healthcheck():
    content = Path("render.yaml").read_text(encoding="utf-8")
    assert "uvicorn api.scan_api:app" in content
    assert "healthCheckPath: /health" in content


def test_requirements_include_api_runtime():
    content = Path("requirements.txt").read_text(encoding="utf-8")
    for package in ("fastapi", "uvicorn", "pydantic"):
        assert package in content
