"""Dependency-free async scheduler for the daily Discord summary."""
from __future__ import annotations

import asyncio
from datetime import datetime
import os
from typing import Any
from zoneinfo import ZoneInfo


class NotificationDailySummaryScheduler:
    MARKET_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(
        self,
        *,
        summary_service: Any,
        policy_service: Any,
        worker_enabled: bool | None = None,
        poll_interval_seconds: float | None = None,
    ) -> None:
        self.summary_service = summary_service
        self.policy_service = policy_service
        self.worker_enabled = (
            self._env_enabled(
                "TRENDFORGE_NOTIFICATION_SUMMARY_WORKER_ENABLED",
                True,
            )
            if worker_enabled is None
            else bool(worker_enabled)
        )
        self.poll_interval_seconds = (
            self._env_float(
                "TRENDFORGE_NOTIFICATION_SUMMARY_POLL_SECONDS",
                60.0,
                minimum=15.0,
                maximum=900.0,
            )
            if poll_interval_seconds is None
            else max(15.0, float(poll_interval_seconds))
        )

        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._running = False
        self.iterations = 0
        self.last_poll_at: str | None = None
        self.last_attempt_date: str | None = None
        self.last_result: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.last_error_at: str | None = None

    @staticmethod
    def _env_enabled(
        name: str,
        default: bool,
    ) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return str(value).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _env_float(
        name: str,
        default: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        raw = os.getenv(name)
        try:
            value = (
                float(raw)
                if raw is not None
                else float(default)
            )
        except (TypeError, ValueError):
            value = float(default)
        return min(max(value, minimum), maximum)

    @classmethod
    def _local_now(
        cls,
        now: datetime | None = None,
    ) -> datetime:
        value = now or datetime.now(cls.MARKET_TZ)
        if value.tzinfo is None:
            return value.replace(tzinfo=cls.MARKET_TZ)
        return value.astimezone(cls.MARKET_TZ)

    @staticmethod
    def _minute_of_day(value: str) -> int:
        hour, minute = str(value).split(":", 1)
        return int(hour) * 60 + int(minute)

    def tick(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = self._local_now(now)
        self.iterations += 1
        self.last_poll_at = current.isoformat()

        if not self.worker_enabled:
            result = {
                "status": "worker_disabled",
                "date": current.date().isoformat(),
            }
            self.last_result = result
            return result

        policy = self.policy_service.current()["policy"]
        summary_policy = policy["daily_summary"]
        if not policy.get("delivery_enabled", True):
            result = {
                "status": "delivery_disabled",
                "date": current.date().isoformat(),
                "scheduled_time_ist": summary_policy[
                    "time_ist"
                ],
            }
            self.last_result = result
            return result

        if not summary_policy["enabled"]:
            result = {
                "status": "summary_disabled",
                "date": current.date().isoformat(),
                "scheduled_time_ist": summary_policy[
                    "time_ist"
                ],
            }
            self.last_result = result
            return result

        today = current.date().isoformat()
        if self.last_attempt_date == today:
            result = {
                "status": "already_checked",
                "date": today,
                "scheduled_time_ist": summary_policy[
                    "time_ist"
                ],
            }
            self.last_result = result
            return result

        current_minute = current.hour * 60 + current.minute
        scheduled_minute = self._minute_of_day(
            summary_policy["time_ist"]
        )
        if current_minute < scheduled_minute:
            result = {
                "status": "before_schedule",
                "date": today,
                "scheduled_time_ist": summary_policy[
                    "time_ist"
                ],
            }
            self.last_result = result
            return result

        self.last_attempt_date = today
        try:
            result = self.summary_service.send(
                summary_date=today,
            )
            self.last_error = None
        except Exception as exc:
            self.last_error = (
                f"{type(exc).__name__}: {exc}"
            )
            self.last_error_at = current.isoformat()
            result = {
                "status": "failed",
                "date": today,
                "error": self.last_error,
            }
        self.last_result = dict(result)
        return dict(result)

    async def _run(self) -> None:
        self._running = True
        try:
            while self._stop_event is not None:
                if self._stop_event.is_set():
                    break
                try:
                    self.tick()
                except Exception as exc:
                    current = datetime.now(self.MARKET_TZ)
                    self.last_error = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    self.last_error_at = current.isoformat()
                    self.last_result = {
                        "status": "failed",
                        "error": self.last_error,
                    }
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self._running = False

    async def start(self) -> bool:
        if not self.worker_enabled:
            return False
        if (
            self._task is not None
            and not self._task.done()
        ):
            return True
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(),
            name="trendforge-notification-daily-summary",
        )
        return True

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await self._task
            finally:
                self._task = None
        self._stop_event = None
        self._running = False

    def health(self) -> dict[str, Any]:
        try:
            policy = self.policy_service.current()["policy"]
            summary_policy = policy["daily_summary"]
            policy_error = None
        except Exception as exc:
            summary_policy = {
                "enabled": False,
                "time_ist": None,
                "skip_empty": True,
            }
            policy_error = f"{type(exc).__name__}: {exc}"

        return {
            "status": (
                "degraded"
                if policy_error
                else "running"
                if self._running
                else "worker_disabled"
                if not self.worker_enabled
                else "idle"
            ),
            "worker_enabled": self.worker_enabled,
            "running": self._running,
            "poll_interval_seconds": self.poll_interval_seconds,
            "summary_enabled": bool(
                summary_policy["enabled"]
            ),
            "scheduled_time_ist": summary_policy[
                "time_ist"
            ],
            "skip_empty": bool(
                summary_policy["skip_empty"]
            ),
            "timezone": "Asia/Kolkata",
            "iterations": self.iterations,
            "last_poll_at": self.last_poll_at,
            "last_attempt_date": self.last_attempt_date,
            "last_result": self.last_result,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "policy_error": policy_error,
            "dependency": "asyncio",
            "apscheduler_required": False,
        }


__all__ = ["NotificationDailySummaryScheduler"]
