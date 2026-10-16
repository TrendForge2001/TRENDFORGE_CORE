"""Repository for canonical notification events."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from database.database import Database


class NotificationEventRepository:
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

    def create(
        self,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        now = self._now()
        self.db.execute(
            """
            INSERT INTO notification_events(
                event_id,
                event_type,
                category,
                severity,
                symbol,
                title,
                message,
                source,
                channel,
                status,
                dedupe_key,
                payload_json,
                error,
                created_at,
                sent_at,
                updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event["event_id"],
                event["event_type"],
                event["category"],
                event["severity"],
                event.get("symbol"),
                event["title"],
                event["message"],
                event["source"],
                event.get("channel", "discord"),
                event["status"],
                event.get("dedupe_key"),
                json.dumps(
                    event.get("payload") or {},
                    sort_keys=True,
                    default=str,
                ),
                event.get("error"),
                event.get("created_at") or now,
                event.get("sent_at"),
                now,
            ),
        )
        return self.get(event["event_id"]) or {}

    def get(
        self,
        event_id: str,
    ) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT *
            FROM notification_events
            WHERE event_id=?
            LIMIT 1
            """,
            (str(event_id or "").strip(),),
        )
        return self._decode(row)

    def update_delivery(
        self,
        event_id: str,
        *,
        status: str,
        error: str | None = None,
        sent_at: str | None = None,
    ) -> dict[str, Any] | None:
        self.db.execute(
            """
            UPDATE notification_events
            SET status=?,
                error=?,
                sent_at=?,
                updated_at=?
            WHERE event_id=?
            """,
            (
                str(status),
                error,
                sent_at,
                self._now(),
                str(event_id),
            ),
        )
        return self.get(event_id)

    def latest(
        self,
        *,
        limit: int = 100,
        category: str | None = None,
        status: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if category:
            clauses.append("category=?")
            params.append(str(category).strip().lower())
        if status:
            clauses.append("status=?")
            params.append(str(status).strip().lower())
        if symbol:
            clauses.append("symbol=?")
            params.append(str(symbol).strip().upper())

        where = (
            "WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )
        query = f"""
            SELECT *
            FROM notification_events
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """
        params.append(max(1, min(int(limit), 500)))
        rows = self.db.fetchall(query, tuple(params))
        return [
            item
            for item in (self._decode(row) for row in rows)
            if item is not None
        ]

    def recent_dedupe(
        self,
        dedupe_key: str,
        *,
        since: str,
    ) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT *
            FROM notification_events
            WHERE dedupe_key=?
              AND created_at>=?
              AND status IN ('sent','recorded')
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (
                str(dedupe_key),
                str(since),
            ),
        )
        return self._decode(row)

    def count(
        self,
        *,
        status: str | None = None,
    ) -> int:
        if status:
            row = self.db.fetchone(
                """
                SELECT COUNT(*) AS total
                FROM notification_events
                WHERE status=?
                """,
                (str(status).strip().lower(),),
            )
        else:
            row = self.db.fetchone(
                """
                SELECT COUNT(*) AS total
                FROM notification_events
                """
            )
        return int(row["total"] or 0) if row else 0

    def category_counts(self) -> dict[str, int]:
        rows = self.db.fetchall(
            """
            SELECT category, COUNT(*) AS total
            FROM notification_events
            GROUP BY category
            ORDER BY total DESC, category
            """
        )
        return {
            str(row["category"]): int(row["total"] or 0)
            for row in rows
        }

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["NotificationEventRepository"]
