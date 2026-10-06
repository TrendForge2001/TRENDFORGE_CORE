"""SQLite-backed fundamental provider for scanner enrichment."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from core.database import database_path
from database.repositories.fundamentals_repository import FundamentalsRepository
from providers.fundamental_mapping import CANONICAL_FIELDS, build_snapshot


class SQLiteFundamentalProvider:
    """Serve imported fundamentals from TrendForge's local SQLite database."""

    NAME = "SQLiteFundamentalProvider"

    def __init__(
        self,
        repository: FundamentalsRepository | None = None,
        *,
        db_path: str | None = None,
        max_age_days: int | None = None,
    ) -> None:
        self._repository_instance = repository
        self.db_path = db_path
        raw_age = (
            max_age_days
            if max_age_days is not None
            else os.getenv("FUNDAMENTALS_MAX_AGE_DAYS", "200")
        )
        self.max_age_days = max(1, int(raw_age))

    def _repository(self) -> FundamentalsRepository:
        if self._repository_instance is None:
            self._repository_instance = FundamentalsRepository(
                db_path=self.db_path or database_path()
            )
        return self._repository_instance

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not value:
            return None
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def get(self, symbol: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        row = self._repository().by_symbol(symbol)
        if row is None:
            return None

        values = {
            "roce": row.get("roce"),
            "roe": row.get("roe"),
            "sales_growth": row.get("sales_growth"),
            "profit_growth": row.get("profit_growth"),
            "eps_growth": row.get("eps_growth"),
            "debt_equity": row.get("debt_to_equity"),
            "promoter_holding": row.get("promoter_holding"),
            "pledged": row.get("pledged"),
        }

        reference = (
            self._parse_timestamp(row.get("as_of"))
            or self._parse_timestamp(row.get("imported_at"))
            or self._parse_timestamp(row.get("updated_at"))
        )
        now = datetime.now(timezone.utc)
        age_days = (now - reference).days if reference is not None else None
        stale = reference is None or age_days is None or age_days > self.max_age_days

        snapshot = build_snapshot(
            provider=self.NAME,
            symbol=row["symbol"],
            values=values,
            as_of=reference.isoformat() if reference is not None else None,
            warnings=(
                ["fundamental_snapshot_stale_or_undated"]
                if stale
                else []
            ),
            extra_meta={
                "stale": stale,
                "age_days": age_days,
                "record_source": row.get("source"),
                "source_file": row.get("source_file"),
                "imported_at": row.get("imported_at"),
                "database_path": self.db_path or database_path(),
            },
        )
        return snapshot

    def get_fundamentals(self, symbol: str) -> dict[str, Any] | None:
        return self.get(symbol)

    def health(self) -> dict[str, Any]:
        count: int | None
        error: str | None = None
        try:
            count = self._repository().count()
        except Exception as exc:
            count = None
            error = str(exc)
        result = {
            "status": "configured",
            "provider": self.NAME,
            "network_probe": False,
            "database_path": self.db_path or database_path(),
            "max_age_days": self.max_age_days,
            "records": count,
        }
        if error:
            result["repository_error"] = error
        return result


__all__ = ["SQLiteFundamentalProvider"]
