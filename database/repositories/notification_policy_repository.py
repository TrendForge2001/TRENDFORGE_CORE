"""Persistence boundary for canonical notification policy preferences."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from database.database import Database


class NotificationPolicyRepository:
    KEY = "notifications.policy.r68_9"

    def __init__(
        self,
        db: Database | None = None,
        db_path: str | None = None,
    ) -> None:
        self._owns_database = db is None
        self.db = db or Database(db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get(self) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT value, updated_at
            FROM settings
            WHERE key=?
            LIMIT 1
            """,
            (self.KEY,),
        )
        if row is None:
            return None
        try:
            value = json.loads(row["value"] or "{}")
        except (TypeError, ValueError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        return {
            "policy": value,
            "updated_at": row["updated_at"],
        }

    def set(
        self,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        now = self._now()
        raw = json.dumps(
            policy,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.db.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (
                self.KEY,
                raw,
                now,
            ),
        )
        return {
            "policy": dict(policy),
            "updated_at": now,
        }

    def reset(self) -> bool:
        cursor = self.db.execute(
            "DELETE FROM settings WHERE key=?",
            (self.KEY,),
        )
        return bool(cursor.rowcount)

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["NotificationPolicyRepository"]
