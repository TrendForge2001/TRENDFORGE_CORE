"""Executable application service wiring for TrendForge."""
from __future__ import annotations

from typing import Any

from config.runtime import runtime_health
from database.database import Database
from database.migrations.run_migrations import run as run_migrations


class ApplicationService:
    """Own process-level resources and initialize persistence safely."""

    def __init__(self, database_factory=Database) -> None:
        self.database_factory = database_factory
        self.database = None

    def start(self) -> dict[str, Any]:
        runtime = runtime_health()
        try:
            self.database = self.database_factory()
            run_migrations(self.database)
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
            "database": {"status": database_status, "migrations": "ready"},
        }

    def stop(self) -> None:
        if self.database is not None:
            self.database.close()
            self.database = None


__all__ = ["ApplicationService"]
