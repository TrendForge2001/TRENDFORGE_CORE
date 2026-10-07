"""Repository for standardized fundamental field evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from database.database import Database
from database.repositories.fundamentals_repository import FundamentalsRepository


class FundamentalFieldEvidenceRepository:
    FIELDS = (
        "symbol",
        "field",
        "value",
        "value_status",
        "period_type",
        "period_label",
        "period_start",
        "period_end",
        "methodology",
        "source_type",
        "source",
        "source_ref",
        "as_of",
        "reason",
        "notes",
        "source_file",
        "recorded_at",
    )

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
            source_type = str(row.get("source_type") or "").strip().upper()
            source = str(row.get("source") or "").strip()
            source_ref = str(row.get("source_ref") or "").strip()
            as_of = str(row.get("as_of") or "").strip()
            status = str(row.get("value_status") or "").strip().upper()
            if (
                not symbol
                or not field
                or not source_type
                or not source
                or not source_ref
                or not as_of
                or not status
            ):
                continue
            value = row.get("value")
            values.append(
                (
                    symbol,
                    field,
                    None if value is None else float(value),
                    status,
                    row.get("period_type"),
                    row.get("period_label"),
                    row.get("period_start"),
                    row.get("period_end"),
                    row.get("methodology"),
                    source_type,
                    source,
                    source_ref,
                    as_of,
                    row.get("reason"),
                    row.get("notes"),
                    row.get("source_file"),
                    row.get("recorded_at") or self._timestamp(),
                )
            )
        if not values:
            return 0
        self.db.executemany(
            """
            INSERT INTO fundamental_field_evidence(
                symbol, field, value, value_status,
                period_type, period_label, period_start, period_end,
                methodology, source_type, source, source_ref, as_of,
                reason, notes, source_file, recorded_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            values,
        )
        return len(values)

    def by_symbol(self, symbol: str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT *
            FROM fundamental_field_evidence
            WHERE symbol=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                FundamentalsRepository.normalize_symbol(symbol),
                max(1, min(int(limit), 2000)),
            ),
        )
        return [dict(row) for row in rows]

    def latest_by_field(self, symbol: str) -> dict[str, dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT *
            FROM fundamental_field_evidence
            WHERE symbol=?
            ORDER BY id DESC
            """,
            (FundamentalsRepository.normalize_symbol(symbol),),
        )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            result.setdefault(str(item["field"]), item)
        return result

    def count(self, symbol: str | None = None) -> int:
        if symbol:
            row = self.db.fetchone(
                "SELECT COUNT(*) AS total FROM fundamental_field_evidence WHERE symbol=?",
                (FundamentalsRepository.normalize_symbol(symbol),),
            )
        else:
            row = self.db.fetchone(
                "SELECT COUNT(*) AS total FROM fundamental_field_evidence"
            )
        return int(row["total"]) if row is not None else 0

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["FundamentalFieldEvidenceRepository"]
