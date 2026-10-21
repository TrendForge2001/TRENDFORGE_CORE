"""SQLite persistence for R72.5 scanner/validation runtime state."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any

from database.database import Database


class StrategyRuntimeStateRepository:
    """Persist restart-safe strategy snapshots and immutable execution claims."""

    SCANNER_KEY = "r72.5.latest_scanner"
    VALIDATION_KEY = "r72.5.latest_validation"

    def __init__(self, db: Database | None = None, db_path: str | None = None):
        self._owns_database = db is None
        self.db = db or Database(db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _encode(payload: dict[str, Any]) -> str:
        return json.dumps(
            payload or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @staticmethod
    def _decode(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        try:
            payload = json.loads(item.pop("payload_json") or "{}")
        except (TypeError, ValueError):
            payload = {}
        item["payload"] = payload if isinstance(payload, dict) else {}
        return item

    def save_state(
        self,
        state_key: str,
        state_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        key = str(state_key or "").strip()
        kind = str(state_type or "").strip().lower()
        if not key or not kind:
            raise ValueError("state_key and state_type are required")
        now = self._now()
        self.db.execute(
            """
            INSERT INTO strategy_runtime_state(
                state_key, state_type, payload_json, created_at, updated_at
            )
            VALUES(?,?,?,?,?)
            ON CONFLICT(state_key) DO UPDATE SET
                state_type=excluded.state_type,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (key, kind, self._encode(payload), now, now),
        )
        return self.load_state(key) or {
            "state_key": key,
            "state_type": kind,
            "payload": dict(payload or {}),
            "created_at": now,
            "updated_at": now,
        }

    def load_state(self, state_key: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT *
            FROM strategy_runtime_state
            WHERE state_key=?
            """,
            (str(state_key or "").strip(),),
        )
        return self._decode(row)

    def latest_by_type(self, state_type: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT *
            FROM strategy_runtime_state
            WHERE state_type=?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (str(state_type or "").strip().lower(),),
        )
        return self._decode(row)

    @staticmethod
    def execution_key(
        scan_run_id: str,
        validation_run_id: str,
        strategy_id: str,
    ) -> str:
        values = [
            str(scan_run_id or "").strip(),
            str(validation_run_id or "").strip(),
            str(strategy_id or "").strip().lower(),
        ]
        if any(not value for value in values):
            raise ValueError(
                "scan_run_id, validation_run_id and strategy_id are required"
            )
        return "r72.5.execution:" + ":".join(values)

    def claim_execution(
        self,
        *,
        scan_run_id: str,
        validation_run_id: str,
        strategy_id: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        key = self.execution_key(
            scan_run_id,
            validation_run_id,
            strategy_id,
        )
        now = self._now()
        try:
            self.db.execute(
                """
                INSERT INTO strategy_runtime_state(
                    state_key, state_type, payload_json, created_at, updated_at
                )
                VALUES(?,?,?,?,?)
                """,
                (
                    key,
                    "execution_claim",
                    self._encode(payload or {}),
                    now,
                    now,
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def has_execution_claim(
        self,
        *,
        scan_run_id: str,
        validation_run_id: str,
        strategy_id: str,
    ) -> bool:
        key = self.execution_key(
            scan_run_id,
            validation_run_id,
            strategy_id,
        )
        row = self.db.fetchone(
            "SELECT 1 AS found FROM strategy_runtime_state WHERE state_key=?",
            (key,),
        )
        return row is not None

    def count(self, state_type: str | None = None) -> int:
        if state_type:
            row = self.db.fetchone(
                """
                SELECT COUNT(*) AS total
                FROM strategy_runtime_state
                WHERE state_type=?
                """,
                (str(state_type).strip().lower(),),
            )
        else:
            row = self.db.fetchone(
                "SELECT COUNT(*) AS total FROM strategy_runtime_state"
            )
        return int(row["total"] or 0) if row is not None else 0

    def health(self) -> dict[str, Any]:
        try:
            rows = self.db.fetchall(
                """
                SELECT state_type, COUNT(*) AS total
                FROM strategy_runtime_state
                GROUP BY state_type
                ORDER BY state_type
                """
            )
            return {
                "status": "ready",
                "storage": "sqlite",
                "database_path": self.db.db_path,
                "records": sum(int(row["total"] or 0) for row in rows),
                "by_type": {
                    str(row["state_type"]): int(row["total"] or 0)
                    for row in rows
                },
            }
        except sqlite3.Error as exc:
            return {
                "status": "degraded",
                "storage": "sqlite",
                "database_path": self.db.db_path,
                "records": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["StrategyRuntimeStateRepository"]
