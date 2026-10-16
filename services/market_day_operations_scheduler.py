"""Dependency-free scheduler for R69.0 market-day operations."""
from __future__ import annotations

import asyncio
from datetime import datetime
import os
from typing import Any
from zoneinfo import ZoneInfo


class MarketDayOperationsScheduler:
    MARKET_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(
        self,
        *,
        operations_service: Any,
        worker_enabled: bool | None = None,
        poll_interval_seconds: float | None = None,
    ) -> None:
        self.operations_service = operations_service
        self.worker_enabled = (
            self._env_enabled(
                "TRENDFORGE_OPERATIONS_WORKER_ENABLED",
                True,
            )
            if worker_enabled is None
            else bool(worker_enabled)
        )
        self.poll_interval_seconds = (
            self._env_float(
                "TRENDFORGE_OPERATIONS_POLL_SECONDS",
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
        self.last_error: str | None = None
        self.last_error_at: str | None = None
        self.last_results: dict[str, Any] = {}

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
        value: datetime | None = None,
    ) -> datetime:
        current = value or datetime.now(cls.MARKET_TZ)
        if current.tzinfo is None:
            return current.replace(tzinfo=cls.MARKET_TZ)
        return current.astimezone(cls.MARKET_TZ)

    @staticmethod
    def _minute(value: str) -> int:
        hour, minute = str(value).split(":", 1)
        return int(hour) * 60 + int(minute)

    @classmethod
    def _inside_window(
        cls,
        current: datetime,
        operation_policy: dict[str, Any],
    ) -> bool:
        scheduled = cls._minute(
            operation_policy["time_ist"]
        )
        grace = int(
            operation_policy["grace_minutes"]
        )
        now_minute = current.hour * 60 + current.minute
        return scheduled <= now_minute <= scheduled + grace

    def tick(
        self,
        *,
        now: datetime | None = None,
        external: bool = False,
    ) -> dict[str, Any]:
        current = self._local_now(now)
        self.iterations += 1
        self.last_poll_at = current.isoformat()

        if not self.worker_enabled and not external:
            result = {
                "status": "worker_disabled",
                "now_ist": current.isoformat(),
                "trigger_source": "internal",
                "operations": {},
            }
            self.last_results = {}
            return result

        policy_state = self.operations_service.policy()
        policy = policy_state["policy"]
        session = self.operations_service.session(
            now=current
        )

        if not policy["automation_enabled"]:
            result = {
                "status": "automation_disabled",
                "now_ist": current.isoformat(),
                "trigger_source": (
                    "external"
                    if external
                    else "internal"
                ),
                "session": session,
                "operations": {},
            }
            self.last_results = {}
            return result

        if (
            policy["market_day_only"]
            and not session["market_day"]
        ):
            result = {
                "status": "non_market_day",
                "now_ist": current.isoformat(),
                "trigger_source": (
                    "external"
                    if external
                    else "internal"
                ),
                "session": session,
                "operations": {},
            }
            self.last_results = {}
            return result

        outcomes: dict[str, Any] = {}
        for operation in self.operations_service.OPERATIONS:
            operation_policy = policy[operation]
            if not operation_policy["enabled"]:
                outcomes[operation] = {
                    "status": "operation_disabled"
                }
                continue
            if not self._inside_window(
                current,
                operation_policy,
            ):
                outcomes[operation] = {
                    "status": "outside_window",
                    "time_ist": operation_policy[
                        "time_ist"
                    ],
                    "grace_minutes": operation_policy[
                        "grace_minutes"
                    ],
                }
                continue

            try:
                outcomes[operation] = (
                    self.operations_service.run(
                        operation,
                        now=current,
                        force=False,
                        scheduled=True,
                    )
                )
            except Exception as exc:
                self.last_error = (
                    f"{type(exc).__name__}: {exc}"
                )
                self.last_error_at = current.isoformat()
                outcomes[operation] = {
                    "status": "failed",
                    "error": self.last_error,
                }

        self.last_results = dict(outcomes)
        if any(
            value.get("status") == "failed"
            for value in outcomes.values()
            if isinstance(value, dict)
        ):
            status = "degraded"
        elif any(
            value.get("status")
            in {"completed", "degraded", "already_completed"}
            for value in outcomes.values()
            if isinstance(value, dict)
        ):
            status = "active_window"
        else:
            status = "idle"

        return {
            "status": status,
            "now_ist": current.isoformat(),
            "trigger_source": (
                "external"
                if external
                else "internal"
            ),
            "session": session,
            "operations": outcomes,
        }

    async def _run(self) -> None:
        self._running = True
        try:
            while self._stop_event is not None:
                if self._stop_event.is_set():
                    break
                try:
                    await asyncio.to_thread(self.tick)
                    self.last_error = None
                except Exception as exc:
                    current = datetime.now(self.MARKET_TZ)
                    self.last_error = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    self.last_error_at = current.isoformat()

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
            name="trendforge-market-day-operations",
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
            policy_state = self.operations_service.policy()
            policy = policy_state["policy"]
            session = self.operations_service.session()
            policy_error = None
        except Exception as exc:
            policy = None
            session = None
            policy_error = (
                f"{type(exc).__name__}: {exc}"
            )

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
            "automation_enabled": (
                bool(policy["automation_enabled"])
                if policy
                else False
            ),
            "morning_time_ist": (
                policy["morning"]["time_ist"]
                if policy
                else None
            ),
            "eod_time_ist": (
                policy["eod"]["time_ist"]
                if policy
                else None
            ),
            "session": session,
            "iterations": self.iterations,
            "last_poll_at": self.last_poll_at,
            "last_results": self.last_results,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "policy_error": policy_error,
            "timezone": "Asia/Kolkata",
            "dependency": "asyncio",
            "apscheduler_required": False,
            "broker_orders_allowed": False,
        }


__all__ = ["MarketDayOperationsScheduler"]
