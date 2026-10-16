from __future__ import annotations

from core.application_factory import ApplicationFactory
from core.database import initialize_database


class FakeProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        raise RuntimeError("not used")


def test_application_factory_shares_one_policy_across_notification_stack(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "trendforge.db"
    monkeypatch.setenv(
        "DATABASE_PATH",
        str(database_path),
    )
    initialize_database(str(database_path))

    factory = ApplicationFactory(
        kite=FakeProvider(),
        yahoo=FakeProvider(),
    )
    policy = factory.notification_policy_service()
    center = factory.notification_center_service()
    daily = factory.notification_daily_summary_service()
    scheduler = factory.notification_summary_scheduler()

    assert center.policy is policy
    assert daily.center is center
    assert daily.policy is policy
    assert scheduler.summary_service is daily
    assert scheduler.policy_service is policy
    assert scheduler.health()["apscheduler_required"] is False

    center.close()
    policy.close()
