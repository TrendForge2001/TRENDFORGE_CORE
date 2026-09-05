"""Production startup import contracts."""


def test_api_application_imports():
    from api.scan_api import app
    assert app is not None


def test_application_health_is_deployment_safe_without_credentials(monkeypatch):
    from config import settings
    from main import health

    for name in (
        "KITE_API_KEY",
        "KITE_API_SECRET",
        "KITE_ACCESS_TOKEN",
        "DISCORD_WEBHOOK",
        "DATABASE_URL",
    ):
        monkeypatch.setattr(settings, name, None)

    report = health()
    assert report["status"] == "healthy"
    assert report["runtime"]["broker_ready"] is False
    assert report["runtime"]["missing_required"] == []


def test_default_scanner_factory_imports():
    from services.default_scanner_factory import build_default_scanner
    assert callable(build_default_scanner)
