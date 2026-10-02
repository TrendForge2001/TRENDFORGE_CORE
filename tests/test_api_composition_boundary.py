from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_api_application_routes_scans_through_application_factory():
    text = _text("api/app.py")
    assert "from core.application_factory import ApplicationFactory" in text
    assert "def get_application()" in text
    assert "_APPLICATION_FACTORY" in text
    assert "return _APPLICATION_FACTORY" in text
    assert "return get_application().scanner_service()" in text


def test_scanner_service_is_injected_and_does_not_construct_pipeline():
    text = _text("api/scanner_service.py")
    assert "def __init__(self, pipeline: FullScannerPipeline)" in text
    assert "FullScannerPipeline()" not in text


def test_asgi_entrypoint_imports_only_canonical_api_boundary():
    text = _text("start.py")
    assert "from api.app import app" in text
    assert "ApplicationFactory(" not in text
    assert "FullScannerPipeline(" not in text


def test_api_boundary_does_not_construct_pipeline_or_engines_directly():
    text = _text("api/app.py")
    forbidden = ("FullScannerPipeline(", "EngineOrchestrator(", "ProviderFactory(")
    assert not [marker for marker in forbidden if marker in text]
