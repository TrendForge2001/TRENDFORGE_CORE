"""Production startup import contracts."""


def test_api_application_imports():
    from api.scan_api import app
    assert app is not None


def test_application_health_imports_without_credentials():
    from main import health
    report = health()
    assert report["status"] in {"healthy", "degraded"}


def test_default_scanner_factory_imports():
    from services.default_scanner_factory import build_default_scanner
    assert callable(build_default_scanner)
