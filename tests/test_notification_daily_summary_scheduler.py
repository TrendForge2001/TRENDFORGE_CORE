from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from services.notification_daily_summary_scheduler import (
    NotificationDailySummaryScheduler,
)


class Policy:
    def __init__(
        self,
        enabled=True,
        time_ist="18:30",
        delivery_enabled=True,
    ):
        self.enabled = enabled
        self.time_ist = time_ist
        self.delivery_enabled = delivery_enabled

    def current(self):
        return {
            "policy": {
                "delivery_enabled": self.delivery_enabled,
                "daily_summary": {
                    "enabled": self.enabled,
                    "time_ist": self.time_ist,
                    "skip_empty": True,
                }
            }
        }


class Summary:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def send(self, *, summary_date):
        self.calls.append(summary_date)
        if self.fail:
            raise RuntimeError("discord summary failed")
        return {
            "status": "sent",
            "date": summary_date,
        }


IST = ZoneInfo("Asia/Kolkata")


def test_tick_waits_until_configured_ist_time():
    summary = Summary()
    scheduler = NotificationDailySummaryScheduler(
        summary_service=summary,
        policy_service=Policy(),
        worker_enabled=True,
    )

    result = scheduler.tick(
        now=datetime(2026, 10, 16, 18, 29, tzinfo=IST)
    )

    assert result["status"] == "before_schedule"
    assert summary.calls == []


def test_tick_sends_once_after_schedule():
    summary = Summary()
    scheduler = NotificationDailySummaryScheduler(
        summary_service=summary,
        policy_service=Policy(),
        worker_enabled=True,
    )

    first = scheduler.tick(
        now=datetime(2026, 10, 16, 18, 30, tzinfo=IST)
    )
    second = scheduler.tick(
        now=datetime(2026, 10, 16, 19, 0, tzinfo=IST)
    )

    assert first["status"] == "sent"
    assert second["status"] == "already_checked"
    assert summary.calls == ["2026-10-16"]


def test_tick_rechecks_on_next_date():
    summary = Summary()
    scheduler = NotificationDailySummaryScheduler(
        summary_service=summary,
        policy_service=Policy(time_ist="00:00"),
        worker_enabled=True,
    )

    scheduler.tick(
        now=datetime(2026, 10, 16, 0, 1, tzinfo=IST)
    )
    scheduler.tick(
        now=datetime(2026, 10, 17, 0, 1, tzinfo=IST)
    )

    assert summary.calls == [
        "2026-10-16",
        "2026-10-17",
    ]


def test_disabled_policy_does_not_send():
    summary = Summary()
    scheduler = NotificationDailySummaryScheduler(
        summary_service=summary,
        policy_service=Policy(enabled=False),
        worker_enabled=True,
    )

    result = scheduler.tick(
        now=datetime(2026, 10, 16, 20, 0, tzinfo=IST)
    )

    assert result["status"] == "summary_disabled"
    assert summary.calls == []


def test_summary_failure_is_observable_not_raised():
    scheduler = NotificationDailySummaryScheduler(
        summary_service=Summary(fail=True),
        policy_service=Policy(),
        worker_enabled=True,
    )

    result = scheduler.tick(
        now=datetime(2026, 10, 16, 18, 30, tzinfo=IST)
    )

    assert result["status"] == "failed"
    assert "discord summary failed" in result["error"]
    assert scheduler.health()["last_error"]


def test_async_worker_start_stop_has_no_external_scheduler_dependency():
    scheduler = NotificationDailySummaryScheduler(
        summary_service=Summary(),
        policy_service=Policy(enabled=False),
        worker_enabled=True,
        poll_interval_seconds=15,
    )

    async def scenario():
        assert await scheduler.start() is True
        await asyncio.sleep(0)
        assert scheduler.health()["running"] is True
        assert scheduler.health()["apscheduler_required"] is False
        await scheduler.stop()
        assert scheduler.health()["running"] is False

    asyncio.run(scenario())


def test_delivery_disabled_does_not_consume_daily_attempt():
    policy = Policy(
        enabled=True,
        delivery_enabled=False,
    )
    summary = Summary()
    scheduler = NotificationDailySummaryScheduler(
        summary_service=summary,
        policy_service=policy,
        worker_enabled=True,
    )

    disabled = scheduler.tick(
        now=datetime(2026, 10, 16, 18, 30, tzinfo=IST)
    )
    assert disabled["status"] == "delivery_disabled"
    assert scheduler.last_attempt_date is None

    policy.delivery_enabled = True
    enabled = scheduler.tick(
        now=datetime(2026, 10, 16, 18, 31, tzinfo=IST)
    )

    assert enabled["status"] == "sent"
    assert scheduler.last_attempt_date == "2026-10-16"
    assert summary.calls == ["2026-10-16"]


def test_health_degrades_if_policy_store_is_unavailable():
    class BrokenPolicy:
        def current(self):
            raise RuntimeError("policy database unavailable")

    scheduler = NotificationDailySummaryScheduler(
        summary_service=Summary(),
        policy_service=BrokenPolicy(),
        worker_enabled=True,
    )

    health = scheduler.health()

    assert health["status"] == "degraded"
    assert health["summary_enabled"] is False
    assert "policy database unavailable" in health["policy_error"]
