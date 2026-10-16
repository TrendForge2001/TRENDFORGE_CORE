"""Repository for R68.6 institutional and sector snapshots."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from database.database import Database


class InstitutionalSectorRepository:
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
        raw = result.pop("payload_json", "{}")
        try:
            payload = json.loads(raw or "{}")
        except (TypeError, ValueError):
            payload = {}
        result["payload"] = (
            payload if isinstance(payload, dict) else {}
        )
        return result

    def save(
        self,
        kind: str,
        snapshot_key: str,
        payload: dict[str, Any],
        *,
        universe: str | None = None,
        sample_size: int | None = None,
    ) -> dict[str, Any]:
        normalized_kind = str(kind or "").strip().lower()
        normalized_key = str(snapshot_key or "").strip().upper()
        if normalized_kind not in {
            "institutional",
            "sector_strength",
        }:
            raise ValueError("unsupported snapshot kind")
        if not normalized_key:
            raise ValueError("snapshot_key is required")

        created_at = self._timestamp()
        self.db.execute(
            """
            INSERT INTO institutional_sector_snapshots(
                kind,
                snapshot_key,
                universe,
                sample_size,
                payload_json,
                created_at
            )
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(kind, snapshot_key) DO UPDATE SET
                universe=excluded.universe,
                sample_size=excluded.sample_size,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                normalized_kind,
                normalized_key,
                universe,
                sample_size,
                json.dumps(
                    payload or {},
                    sort_keys=True,
                    default=str,
                ),
                created_at,
            ),
        )
        return self.get(
            normalized_kind,
            normalized_key,
        ) or {}

    def get(
        self,
        kind: str,
        snapshot_key: str,
    ) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT *
            FROM institutional_sector_snapshots
            WHERE kind=? AND snapshot_key=?
            LIMIT 1
            """,
            (
                str(kind or "").strip().lower(),
                str(snapshot_key or "").strip().upper(),
            ),
        )
        return self._decode(row)

    def list(
        self,
        *,
        kind: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT *
            FROM institutional_sector_snapshots
            WHERE kind=?
            ORDER BY created_at DESC, snapshot_key
            LIMIT ?
            """,
            (
                str(kind or "").strip().lower(),
                max(1, min(int(limit), 500)),
            ),
        )
        return [
            item
            for item in (self._decode(row) for row in rows)
            if item is not None
        ]

    def count(self, *, kind: str) -> int:
        row = self.db.fetchone(
            """
            SELECT COUNT(*) AS total
            FROM institutional_sector_snapshots
            WHERE kind=?
            """,
            (str(kind or "").strip().lower(),),
        )
        return int(row["total"] or 0) if row is not None else 0

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["InstitutionalSectorRepository"]
