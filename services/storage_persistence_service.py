"""Stable SQLite storage identity and boot evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from typing import Any
from uuid import uuid4

from database.database import Database


class StoragePersistenceService:
    """Record a stable database identity and production boot counter."""

    def __init__(
        self,
        db: Database | None = None,
        db_path: str | None = None,
    ) -> None:
        self._owns_database = db is None
        self.db = db or Database(db_path)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _decode(row) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result.pop("singleton", None)
        result["boot_count"] = int(result.get("boot_count") or 0)
        return result

    def identity(self) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT singleton, storage_id, created_at, first_boot_at,
                   last_boot_at, boot_count, last_git_commit,
                   last_service_id
            FROM storage_runtime_state
            WHERE singleton=1
            """
        )
        return self._decode(row)

    def record_boot(
        self,
        *,
        git_commit: str | None = None,
        service_id: str | None = None,
    ) -> dict[str, Any]:
        now = self._timestamp()
        current = self.identity()

        if current is None:
            self.db.execute(
                """
                INSERT INTO storage_runtime_state(
                    singleton, storage_id, created_at, first_boot_at,
                    last_boot_at, boot_count, last_git_commit,
                    last_service_id
                )
                VALUES(1,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid4()),
                    now,
                    now,
                    now,
                    1,
                    git_commit,
                    service_id,
                ),
            )
        else:
            self.db.execute(
                """
                UPDATE storage_runtime_state
                SET last_boot_at=?,
                    boot_count=boot_count + 1,
                    last_git_commit=?,
                    last_service_id=?
                WHERE singleton=1
                """,
                (now, git_commit, service_id),
            )

        result = self.identity()
        if result is None:
            raise RuntimeError("Storage identity could not be recorded")
        return {
            "status": "recorded",
            **result,
        }

    def health(self) -> dict[str, Any]:
        try:
            identity = self.identity()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return {
                    "status": "not_initialized",
                    "reason": "schema_not_initialized",
                }
            return {
                "status": "degraded",
                "reason": "sqlite_operational_error",
                "error": str(exc),
            }
        except sqlite3.Error as exc:
            return {
                "status": "degraded",
                "reason": "sqlite_error",
                "error": str(exc),
            }

        if identity is None:
            return {
                "status": "not_recorded",
                "boot_count": 0,
            }
        return {
            "status": "ready",
            **identity,
        }

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["StoragePersistenceService"]
