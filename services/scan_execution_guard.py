"""Application-scoped single-flight guard for expensive universe scans."""
from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
from typing import Any


class ScanExecutionGuard:
    """Allow at most one protected universe scan per application instance."""

    def __init__(self) -> None:
        self._execution_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active: dict[str, Any] | None = None
        self._last_completed: dict[str, Any] | None = None

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def try_start(self, run_id: str) -> bool:
        run_id = str(run_id or "").strip()
        if not run_id:
            raise ValueError("run_id is required")

        if not self._execution_lock.acquire(blocking=False):
            return False

        now = self._timestamp()
        with self._state_lock:
            self._active = {
                "run_id": run_id,
                "started_at": now,
                "started_monotonic": time.monotonic(),
            }
        return True

    def finish(self, run_id: str, outcome: str) -> None:
        run_id = str(run_id or "").strip()
        should_release = False

        with self._state_lock:
            active = self._active
            if active is None or active.get("run_id") != run_id:
                return

            started_monotonic = float(
                active.get("started_monotonic") or time.monotonic()
            )
            self._last_completed = {
                "run_id": run_id,
                "started_at": active.get("started_at"),
                "finished_at": self._timestamp(),
                "duration_sec": round(
                    max(0.0, time.monotonic() - started_monotonic),
                    3,
                ),
                "outcome": str(outcome or "unknown"),
            }
            self._active = None
            should_release = True

        if should_release:
            self._execution_lock.release()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            active = dict(self._active) if self._active else None
            last_completed = (
                dict(self._last_completed)
                if self._last_completed
                else None
            )

        if active is not None:
            started_monotonic = float(
                active.pop("started_monotonic", time.monotonic())
            )
            active["elapsed_sec"] = round(
                max(0.0, time.monotonic() - started_monotonic),
                3,
            )

        return {
            "status": "busy" if active else "idle",
            "single_flight": True,
            "active": active,
            "last_completed": last_completed,
        }


__all__ = ["ScanExecutionGuard"]
