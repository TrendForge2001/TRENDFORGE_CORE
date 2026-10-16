"""Persistence boundary for canonical news/corporate-action evidence."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from database.database import Database


class IntelligenceEventRepository:
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
        raw = result.pop("details_json", "{}")
        try:
            details = json.loads(raw or "{}")
        except (TypeError, ValueError):
            details = {}
        result["details"] = (
            details if isinstance(details, dict) else {}
        )
        return result

    def upsert(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event or {})
        event_key = str(payload.get("event_key") or "").strip()
        domain = str(payload.get("domain") or "").strip().lower()
        symbol = str(payload.get("symbol") or "").strip().upper()

        if not event_key:
            raise ValueError("event_key is required")
        if domain not in {"news", "corporate_action"}:
            raise ValueError(
                "domain must be news or corporate_action"
            )
        if not symbol:
            raise ValueError("symbol is required")

        fetched_at = str(
            payload.get("fetched_at") or self._timestamp()
        )
        details = payload.get("details")
        if not isinstance(details, dict):
            details = {}

        self.db.execute(
            """
            INSERT INTO intelligence_events(
                event_key,
                domain,
                symbol,
                event_type,
                headline,
                summary,
                source,
                publisher,
                url,
                event_at,
                sentiment_label,
                sentiment_score,
                impact_score,
                details_json,
                fetched_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(event_key) DO UPDATE SET
                event_type=excluded.event_type,
                headline=excluded.headline,
                summary=excluded.summary,
                source=excluded.source,
                publisher=excluded.publisher,
                url=excluded.url,
                event_at=excluded.event_at,
                sentiment_label=excluded.sentiment_label,
                sentiment_score=excluded.sentiment_score,
                impact_score=excluded.impact_score,
                details_json=excluded.details_json,
                fetched_at=excluded.fetched_at
            """,
            (
                event_key,
                domain,
                symbol,
                payload.get("event_type"),
                payload.get("headline"),
                payload.get("summary"),
                payload.get("source"),
                payload.get("publisher"),
                payload.get("url"),
                payload.get("event_at"),
                payload.get("sentiment_label"),
                payload.get("sentiment_score"),
                payload.get("impact_score"),
                json.dumps(details, sort_keys=True, default=str),
                fetched_at,
            ),
        )
        return self.by_key(event_key) or payload

    def by_key(self, event_key: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT *
            FROM intelligence_events
            WHERE event_key=?
            LIMIT 1
            """,
            (str(event_key or "").strip(),),
        )
        return self._decode(row)

    def list(
        self,
        *,
        domain: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []

        if domain:
            clauses.append("domain=?")
            values.append(str(domain).strip().lower())
        if symbol:
            clauses.append("symbol=?")
            values.append(str(symbol).strip().upper())

        where = (
            " WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )
        values.append(max(1, min(int(limit), 500)))

        rows = self.db.fetchall(
            """
            SELECT *
            FROM intelligence_events
            """
            + where
            + """
            ORDER BY
                CASE WHEN event_at IS NULL OR event_at='' THEN 1 ELSE 0 END,
                event_at DESC,
                id DESC
            LIMIT ?
            """,
            tuple(values),
        )
        return [
            item
            for item in (self._decode(row) for row in rows)
            if item is not None
        ]

    def count(
        self,
        *,
        domain: str | None = None,
        symbol: str | None = None,
    ) -> int:
        clauses: list[str] = []
        values: list[Any] = []

        if domain:
            clauses.append("domain=?")
            values.append(str(domain).strip().lower())
        if symbol:
            clauses.append("symbol=?")
            values.append(str(symbol).strip().upper())

        where = (
            " WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )
        row = self.db.fetchone(
            "SELECT COUNT(*) AS total "
            "FROM intelligence_events"
            + where,
            tuple(values),
        )
        return int(row["total"] or 0) if row is not None else 0

    def latest_fetch_at(
        self,
        *,
        domain: str,
        symbol: str,
    ) -> str | None:
        row = self.db.fetchone(
            """
            SELECT MAX(fetched_at) AS fetched_at
            FROM intelligence_events
            WHERE domain=? AND symbol=?
            """,
            (
                str(domain).strip().lower(),
                str(symbol).strip().upper(),
            ),
        )
        if row is None:
            return None
        value = row["fetched_at"]
        return str(value) if value else None

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["IntelligenceEventRepository"]
