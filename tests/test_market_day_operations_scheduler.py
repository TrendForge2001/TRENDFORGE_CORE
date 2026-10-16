from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from services.market_day_operations_scheduler import (
    MarketDayOperationsScheduler,
)


IST = ZoneInfo("Asia/Kolkata")


class Operations:
    OPERATIONS = ("morning", "eod")

    def __init__(self):
        self.policy_value = {
            "automation_enabled": True,
            "market_day_only": True,
            "morning": {
                "enabled": True,
                "time_ist": "08:45",
                "grace_minutes": 30,
            },
            "eod": {
                "enabled": True,
                "time_ist": "15:45",
                "grace_minutes": 30,
            },
        }
        self.market_day = True
        self.calls = []
        self.fail = False

    def policy(self):
        return {"policy": self.policy_value}

    def session(self, *, now=None):
        return {
            "market_day": self.market_day,
            "date_ist": now.date().isoformat() if now else "2026-10-16",
            "phase": "pre_market",
        }

    def run(
        self,
        operation,
        *,
        now=None,
        force=False,
        scheduled=False,
    ):
        self.calls.append(
            {
                "operation": operation,
                "scheduled": scheduled,
                "force": force,
                "now": now,
            }
        )
        if self.fail:
            raise RuntimeError("operation failed")
        return {
            "status": "completed",
            "operation": operation,
            "date_ist": now.date().isoformat(),
        }


def at(hour, minute, *, day=16):
    return datetime(
        2026,
        10,
        day,
        hour,
        minute,
        tzinfo=IST,
    )


def test_scheduler_does_nothing_when_automation_disabled():
    ops = Operations()
    ops.policy_value["automation_enabled"] = False
    scheduler = MarketDayOperationsScheduler(
        operations_service=ops,
        worker_enabled=True,
    )

    result = scheduler.tick(now=at(8, 45))

    assert result["status"] == "automation_disabled"
    assert ops.calls == []


def test_scheduler_runs_morning_inside_bounded_window():
    ops = Operations()
    scheduler = MarketDayOperationsScheduler(
        operations_service=ops,
        worker_enabled=True,
    )

    before = scheduler.tick(now=at(8, 44))
    inside = scheduler.tick(now=at(8, 45))
    edge = scheduler.tick(now=at(9, 15))
    after = scheduler.tick(now=at(9, 16))

    assert before["operations"]["morning"]["status"] == "outside_window"
    assert inside["operations"]["morning"]["status"] == "completed"
    assert edge["operations"]["morning"]["status"] == "completed"
    assert after["operations"]["morning"]["status"] == "outside_window"
    assert [call["operation"] for call in ops.calls] == [
        "morning",
        "morning",
    ]


def test_scheduler_runs_eod_only_in_eod_window():
    ops = Operations()
    scheduler = MarketDayOperationsScheduler(
        operations_service=ops,
        worker_enabled=True,
    )

    result = scheduler.tick(now=at(15, 45))

    assert result["operations"]["eod"]["status"] == "completed"
    assert result["operations"]["morning"]["status"] == "outside_window"
    assert ops.calls[0]["operation"] == "eod"
    assert ops.calls[0]["scheduled"] is True


def test_non_market_day_blocks_scheduler():
    ops = Operations()
    ops.market_day = False
    scheduler = MarketDayOperationsScheduler(
        operations_service=ops,
        worker_enabled=True,
    )

    result = scheduler.tick(now=at(8, 45, day=17))

    assert result["status"] == "non_market_day"
    assert ops.calls == []


def test_operation_failure_degrades_tick_without_raising():
    ops = Operations()
    ops.fail = True
    scheduler = MarketDayOperationsScheduler(
        operations_service=ops,
        worker_enabled=True,
    )

    result = scheduler.tick(now=at(8, 45))

    assert result["status"] == "degraded"
    assert result["operations"]["morning"]["status"] == "failed"
    assert "operation failed" in result["operations"]["morning"]["error"]


def test_async_worker_start_stop_uses_only_asyncio():
    ops = Operations()
    ops.policy_value["automation_enabled"] = False
    scheduler = MarketDayOperationsScheduler(
        operations_service=ops,
        worker_enabled=True,
        poll_interval_seconds=15,
    )

    async def scenario():
        assert await scheduler.start() is True
        await asyncio.sleep(0)
        assert scheduler.health()["running"] is True
        assert scheduler.health()["apscheduler_required"] is False
        assert scheduler.health()["broker_orders_allowed"] is False
        await scheduler.stop()
        assert scheduler.health()["running"] is False

    asyncio.run(scenario())


def test_health_degrades_when_policy_store_is_unavailable():
    class Broken:
        OPERATIONS = ("morning", "eod")

        def policy(self):
            raise RuntimeError("settings unavailable")

    scheduler = MarketDayOperationsScheduler(
        operations_service=Broken(),
        worker_enabled=True,
    )

    health = scheduler.health()

    assert health["status"] == "degraded"
    assert "settings unavailable" in health["policy_error"]


def test_external_tick_runs_even_when_internal_worker_disabled():
    ops = Operations()
    scheduler = MarketDayOperationsScheduler(
        operations_service=ops,
        worker_enabled=False,
    )

    internal = scheduler.tick(
        now=at(8, 45),
    )
    external = scheduler.tick(
        now=at(8, 45),
        external=True,
    )

    assert internal["status"] == "worker_disabled"
    assert internal["trigger_source"] == "internal"
    assert external["status"] == "active_window"
    assert external["trigger_source"] == "external"
    assert external["operations"]["morning"]["status"] == "completed"
    assert [call["operation"] for call in ops.calls] == [
        "morning"
    ]
