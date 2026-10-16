"""Persistence for R69.0 scheduled-operation policy and run evidence."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from database.database import Database


class MarketDayOperationsRepository:
    POLICY_KEY = "operations.policy.r69_0"
    RUNS_KEY = "operations.runs.r69_0"
    MAX_RUNS = 100

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

    def _get_json(
        self,
        key: str,
        default: Any,
    ) -> tuple[Any, str | None]:
        row = self.db.fetchone(
            """
            SELECT value, updated_at
            FROM settings
            WHERE key=?
            LIMIT 1
            """,
            (key,),
        )
        if row is None:
            return default, None
        try:
            value = json.loads(row["value"] or "")
        except (TypeError, ValueError):
            value = default
        return value, row["updated_at"]

    def _set_json(
        self,
        key: str,
        value: Any,
    ) -> str:
        now = self._now()
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        self.db.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (key, raw, now),
        )
        return now

    def policy(self) -> dict[str, Any] | None:
        value, updated_at = self._get_json(
            self.POLICY_KEY,
            None,
        )
        if not isinstance(value, dict):
            return None
        return {
            "policy": value,
            "updated_at": updated_at,
        }

    def set_policy(
        self,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        updated_at = self._set_json(
            self.POLICY_KEY,
            policy,
        )
        return {
            "policy": dict(policy),
            "updated_at": updated_at,
        }

    def reset_policy(self) -> bool:
        cursor = self.db.execute(
            "DELETE FROM settings WHERE key=?",
            (self.POLICY_KEY,),
        )
        return bool(cursor.rowcount)

    def runs(
        self,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        value, _ = self._get_json(
            self.RUNS_KEY,
            [],
        )
        rows = (
            value
            if isinstance(value, list)
            else []
        )
        normalized = [
            dict(row)
            for row in rows
            if isinstance(row, dict)
        ]
        return normalized[-max(1, min(int(limit), self.MAX_RUNS)):][::-1]

    def record_run(
        self,
        run: dict[str, Any],
    ) -> dict[str, Any]:
        value, _ = self._get_json(
            self.RUNS_KEY,
            [],
        )
        rows = (
            list(value)
            if isinstance(value, list)
            else []
        )
        rows.append(dict(run))
        rows = rows[-self.MAX_RUNS:]
        self._set_json(
            self.RUNS_KEY,
            rows,
        )
        return dict(run)

    def successful_run(
        self,
        operation: str,
        date_ist: str,
    ) -> dict[str, Any] | None:
        for row in self.runs(limit=self.MAX_RUNS):
            if (
                row.get("operation") == operation
                and row.get("date_ist") == date_ist
                and row.get("status") in {
                    "completed",
                    "degraded",
                }
            ):
                return row
        return None

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["MarketDayOperationsRepository"]
