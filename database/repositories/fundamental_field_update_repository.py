"""Repository for per-field fundamental completion audit history."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from database.database import Database
from database.repositories.fundamentals_repository import FundamentalsRepository


class FundamentalFieldUpdateRepository:
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

    def add_many(self, rows: Iterable[dict[str, Any]]) -> int:
        values = []
        for row in rows:
            symbol = FundamentalsRepository.normalize_symbol(row.get("symbol"))
            field = str(row.get("field") or "").strip()
            value = row.get("value")
            if not symbol or not field or value is None:
                continue
            values.append(
                (
                    symbol,
                    field,
                    float(value),
                    row.get("source"),
                    row.get("source_file"),
                    row.get("as_of"),
                    row.get("imported_at") or self._timestamp(),
                )
            )
        if not values:
            return 0
        self.db.executemany(
            """
            INSERT INTO fundamental_field_updates(
                symbol, field, value, source, source_file, as_of, imported_at
            )
            VALUES(?,?,?,?,?,?,?)
            """,
            values,
        )
        return len(values)

    def by_symbol(self, symbol: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT id, symbol, field, value, source, source_file, as_of, imported_at
            FROM fundamental_field_updates
            WHERE symbol=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                FundamentalsRepository.normalize_symbol(symbol),
                max(1, min(int(limit), 1000)),
            ),
        )
        return [dict(row) for row in rows]

    def count(self, symbol: str | None = None) -> int:
        if symbol:
            row = self.db.fetchone(
                "SELECT COUNT(*) AS total FROM fundamental_field_updates WHERE symbol=?",
                (FundamentalsRepository.normalize_symbol(symbol),),
            )
        else:
            row = self.db.fetchone(
                "SELECT COUNT(*) AS total FROM fundamental_field_updates"
            )
        return int(row["total"]) if row is not None else 0

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["FundamentalFieldUpdateRepository"]
