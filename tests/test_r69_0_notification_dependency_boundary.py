from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8").lower()


def test_r69_0_canonical_scheduler_does_not_import_apscheduler():
    for path in (
        "services/market_day_service.py",
        "services/market_day_operations_service.py",
        "services/market_day_operations_scheduler.py",
        "core/application_factory.py",
        "api/app.py",
    ):
        value = source(path)
        assert "from apscheduler" not in value
        assert "import apscheduler" not in value


def test_r69_0_does_not_add_scheduler_dependency():
    assert "apscheduler==" not in source(
        "requirements-production.lock"
    )
    assert "apscheduler>=" not in source(
        "requirements.txt"
    )
