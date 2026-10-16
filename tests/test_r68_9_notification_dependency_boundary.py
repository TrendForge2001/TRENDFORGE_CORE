from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8").lower()


def test_canonical_r68_9_notification_stack_does_not_import_apscheduler():
    for path in (
        "services/notification_policy_service.py",
        "services/notification_daily_summary_service.py",
        "services/notification_daily_summary_scheduler.py",
        "services/notification_center_service.py",
        "core/application_factory.py",
        "api/app.py",
    ):
        source = _text(path)
        assert "from apscheduler" not in source
        assert "import apscheduler" not in source


def test_production_dependency_lock_does_not_need_apscheduler():
    lock = _text("requirements-production.lock")
    requirements = _text("requirements.txt")

    assert "apscheduler==" not in lock
    assert "apscheduler>=" not in requirements
