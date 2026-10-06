"""SQLite repository for normalized fundamental snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from database.database import Database


class FundamentalsRepository:
    """Persist canonical fundamentals independently from import source."""

    FIELDS = (
        "symbol",
        "market_cap",
        "pe",
        "pb",
        "eps",
        "roe",
        "roce",
        "debt_to_equity",
        "sales_growth",
        "profit_growth",
        "eps_growth",
        "promoter_holding",
        "pledged",
        "fii_holding",
        "dii_holding",
        "dividend_yield",
        "current_ratio",
        "quick_ratio",
        "book_value",
        "face_value",
        "sector",
        "industry",
        "source",
        "source_file",
        "as_of",
        "imported_at",
        "updated_at",
    )

    def __init__(self, db: Database | None = None, db_path: str | None = None):
        self._owns_database = db is None
        self.db = db or Database(db_path)

    @staticmethod
    def normalize_symbol(symbol: Any) -> str:
        value = str(symbol or "").strip().upper()
        if value.startswith("NSE:"):
            value = value[4:]
        if value.endswith(".NS"):
            value = value[:-3]
        return value

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _upsert_sql(cls) -> str:
        columns = ", ".join(cls.FIELDS)
        placeholders = ", ".join("?" for _ in cls.FIELDS)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in cls.FIELDS
            if field != "symbol"
        )
        return (
            f"INSERT INTO fundamentals ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(symbol) DO UPDATE SET {updates}"
        )

    def _merged_record(self, data: dict[str, Any]) -> dict[str, Any]:
        symbol = self.normalize_symbol(data.get("symbol"))
        if not symbol:
            raise ValueError("Fundamental record requires symbol")

        existing = self.by_symbol(symbol) or {}
        record = {field: existing.get(field) for field in self.FIELDS}
        record["symbol"] = symbol

        # Fundamental datasets are often partial. Missing values must never
        # erase previously verified values from another import/manual update.
        for field in self.FIELDS:
            if field in {"symbol", "imported_at", "updated_at"}:
                continue
            value = data.get(field)
            if value is not None and value != "":
                record[field] = value

        now = self._timestamp()
        record["imported_at"] = (
            data.get("imported_at")
            or existing.get("imported_at")
            or now
        )
        record["updated_at"] = now
        return record

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        """Merge non-null fields into a symbol and persist the full snapshot."""
        record = self._merged_record(data)
        self.db.execute(
            self._upsert_sql(),
            tuple(record[field] for field in self.FIELDS),
        )
        return record

    def save_many(self, rows: Iterable[dict[str, Any]]) -> int:
        """Bulk merge rows without replacing existing values with nulls."""
        records = [self._merged_record(dict(row)) for row in rows]
        if not records:
            return 0
        self.db.executemany(
            self._upsert_sql(),
            [tuple(record[field] for field in self.FIELDS) for record in records],
        )
        return len(records)

    def by_symbol(self, symbol: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM fundamentals WHERE symbol=?",
            (self.normalize_symbol(symbol),),
        )
        return dict(row) if row is not None else None

    def exists(self, symbol: str) -> bool:
        return self.by_symbol(symbol) is not None

    def delete(self, symbol: str) -> None:
        self.db.execute(
            "DELETE FROM fundamentals WHERE symbol=?",
            (self.normalize_symbol(symbol),),
        )

    def clear(self) -> None:
        self.db.execute("DELETE FROM fundamentals")

    def latest(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT * FROM fundamentals ORDER BY updated_at DESC LIMIT ?",
            (max(1, int(limit)),),
        )
        return [dict(row) for row in rows]

    def all(self, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT * FROM fundamentals ORDER BY symbol ASC LIMIT ?",
            (max(1, int(limit)),),
        )
        return [dict(row) for row in rows]

    def count(self) -> int:
        row = self.db.fetchone("SELECT COUNT(*) AS total FROM fundamentals")
        return int(row["total"]) if row is not None else 0

    def pe_less_than(self, value: float):
        return self.db.fetchall(
            "SELECT * FROM fundamentals WHERE pe<=? ORDER BY pe",
            (value,),
        )

    def roe_greater_than(self, value: float):
        return self.db.fetchall(
            "SELECT * FROM fundamentals WHERE roe>=? ORDER BY roe DESC",
            (value,),
        )

    def roce_greater_than(self, value: float):
        return self.db.fetchall(
            "SELECT * FROM fundamentals WHERE roce>=? ORDER BY roce DESC",
            (value,),
        )

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["FundamentalsRepository"]
