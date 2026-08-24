"""Executable application service wiring for TrendForge."""
from __future__ import annotations

from typing import Any

from config.runtime import runtime_health
from database.database import Database


class ApplicationService:
    """Own process-level resources and expose safe lifecycle operations."""

    def __init__(self, database_factory=Database) -> None:
        self.database_factory = database_factory
        self.database = None

    def start(self) -> dict[str, Any]:
        runtime = runtime_health()
        try:
            self.database = self.database_factory()
            database_status = "connected"
        except Exception as exc:
            database_status = "unavailable"
            return {
                "status": "degraded",
                "runtime": runtime,
                "database": {"status": database_status, "error": str(exc)},
            }
        return {
            "status": "healthy" if runtime["status"] == "healthy" else "degraded",
            "runtime": runtime,
            "database": {"status": database_status},
        }

    def stop(self) -> None:
        if self.database is not None:
            self.database.close()
            self.database = None


__all__ = ["ApplicationService"]
