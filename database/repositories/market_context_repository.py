"""SQLite persistence for latest market breadth/regime snapshots."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from database.database import Database


class MarketContextRepository:
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
        payload: dict[str, Any],
        *,
        universe: str,
        sample_size: int,
    ) -> dict[str, Any]:
        key = str(kind or "").strip().lower()
        if key not in {"breadth", "regime"}:
            raise ValueError(
                "market context kind must be breadth or regime"
            )
        created_at = self._timestamp()
        self.db.execute(
            """
            INSERT INTO market_context_snapshots(
                kind, universe, sample_size,
                payload_json, created_at
            )
            VALUES(?,?,?,?,?)
            ON CONFLICT(kind) DO UPDATE SET
                universe=excluded.universe,
                sample_size=excluded.sample_size,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                key,
                str(universe or "NIFTY 500"),
                int(sample_size),
                json.dumps(payload, sort_keys=True),
                created_at,
            ),
        )
        return self.get(key) or {}

    def get(self, kind: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT *
            FROM market_context_snapshots
            WHERE kind=?
            """,
            (str(kind or "").strip().lower(),),
        )
        return self._decode(row)

    def all(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT *
            FROM market_context_snapshots
            ORDER BY kind
            """
        )
        return [
            item
            for item in (
                self._decode(row) for row in rows
            )
            if item is not None
        ]

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["MarketContextRepository"]
