"""Fundamental Data Manager for manual/file-managed SQLite fundamentals."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO, StringIO
import os
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from database.repositories.fundamentals_repository import FundamentalsRepository
from engines.fundamental_contract import FundamentalInputContract
from services.fundamental_import_service import FundamentalFileImportService


class FundamentalDataManager:
    """Own manual edits, file imports, quality reporting and templates."""

    REQUIRED_FIELDS = tuple(FundamentalInputContract.REQUIRED)
    STORAGE_FIELD = {
        "roce": "roce",
        "roe": "roe",
        "sales_growth": "sales_growth",
        "profit_growth": "profit_growth",
        "eps_growth": "eps_growth",
        "debt_equity": "debt_to_equity",
        "promoter_holding": "promoter_holding",
        "pledged": "pledged",
    }
    TEMPLATE_COLUMNS = (
        "Symbol",
        "ROCE",
        "ROE",
        "Sales Growth",
        "Profit Growth",
        "EPS Growth",
        "Debt/Equity",
        "Promoter Holding",
        "Pledged %",
        "Source",
        "As Of",
    )

    def __init__(
        self,
        repository: FundamentalsRepository | None = None,
        *,
        db_path: str | None = None,
        max_age_days: int | None = None,
    ) -> None:
        self.repository = repository or FundamentalsRepository(db_path=db_path)
        raw_age = (
            max_age_days
            if max_age_days is not None
            else os.getenv("FUNDAMENTALS_MAX_AGE_DAYS", "200")
        )
        self.max_age_days = max(1, int(raw_age))
        self.contract = FundamentalInputContract()

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        try:
            parsed = datetime.fromisoformat(
                str(value).strip().replace("Z", "+00:00")
            )
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _canonical(cls, row: Mapping[str, Any] | None) -> dict[str, Any]:
        row = row or {}
        return {
            field: row.get(storage)
            for field, storage in cls.STORAGE_FIELD.items()
        }

    def _freshness(self, row: Mapping[str, Any]) -> dict[str, Any]:
        reference = (
            self._parse_timestamp(row.get("as_of"))
            or self._parse_timestamp(row.get("imported_at"))
            or self._parse_timestamp(row.get("updated_at"))
        )
        if reference is None:
            return {
                "as_of": None,
                "age_days": None,
                "stale": True,
                "max_age_days": self.max_age_days,
            }
        age_days = max(
            0,
            int((datetime.now(timezone.utc) - reference).total_seconds() // 86400),
        )
        return {
            "as_of": reference.isoformat(),
            "age_days": age_days,
            "stale": age_days > self.max_age_days,
            "max_age_days": self.max_age_days,
        }

    def quality(self, row: Mapping[str, Any]) -> dict[str, Any]:
        canonical = self._canonical(row)
        report = self.contract.validate(canonical)
        present = [
            field
            for field in self.REQUIRED_FIELDS
            if canonical.get(field) is not None
        ]
        completeness = round(
            len(present) / len(self.REQUIRED_FIELDS) * 100,
            2,
        )
        freshness = self._freshness(row)
        ready = report.ready and not freshness["stale"]
        warnings = list(report.warnings)
        if freshness["stale"]:
            warnings.append("Fundamental snapshot is stale or undated")
        return {
            "ready": ready,
            "contract_ready": report.ready,
            "completeness_pct": completeness,
            "present": present,
            "missing": list(report.missing),
            "invalid": list(report.invalid),
            "warnings": list(dict.fromkeys(warnings)),
            "stale": freshness["stale"],
            "age_days": freshness["age_days"],
            "max_age_days": freshness["max_age_days"],
            "as_of": freshness["as_of"],
            "source": row.get("source"),
            "source_file": row.get("source_file"),
            "imported_at": row.get("imported_at"),
            "updated_at": row.get("updated_at"),
        }

    def inspect(self, symbol: str) -> dict[str, Any] | None:
        row = self.repository.by_symbol(symbol)
        if row is None:
            return None
        canonical = self._canonical(row)
        return {
            "symbol": row["symbol"],
            "fundamentals": canonical,
            "quality": self.quality(row),
            "metadata": {
                "source": row.get("source"),
                "source_file": row.get("source_file"),
                "as_of": row.get("as_of"),
                "imported_at": row.get("imported_at"),
                "updated_at": row.get("updated_at"),
            },
        }

    def upsert(
        self,
        symbol: str,
        values: Mapping[str, Any],
        *,
        source: str = "manual",
        as_of: str | None = None,
    ) -> dict[str, Any]:
        normalized = FundamentalsRepository.normalize_symbol(symbol)
        if not normalized:
            raise ValueError("Symbol is required")

        updates: dict[str, Any] = {
            "symbol": normalized,
            "source": str(source or "manual"),
            "as_of": as_of or datetime.now(timezone.utc).isoformat(),
        }
        for field, storage in self.STORAGE_FIELD.items():
            if field in values and values[field] is not None:
                updates[storage] = values[field]
            elif storage in values and values[storage] is not None:
                updates[storage] = values[storage]

        existing = self.repository.by_symbol(normalized) or {}
        candidate = dict(existing)
        candidate.update(
            {
                key: value
                for key, value in updates.items()
                if value is not None and value != ""
            }
        )
        validation = self.contract.validate(self._canonical(candidate))
        if validation.invalid:
            raise ValueError(
                "Invalid fundamental fields: "
                + ", ".join(validation.invalid)
            )

        self.repository.save(updates)
        result = self.inspect(normalized)
        if result is None:  # pragma: no cover - repository persistence invariant
            raise RuntimeError("Fundamental record was not persisted")
        return result

    def import_file(
        self,
        path: str | Path,
        *,
        source: str = "manual_file",
        symbol_column: str | None = None,
        field_map: str | Mapping[str, Any] | None = None,
        sheet_name: str | int | None = 0,
        as_of: str | None = None,
        source_file_name: str | None = None,
    ) -> dict[str, Any]:
        importer = FundamentalFileImportService(self.repository)
        report = importer.import_file(
            path,
            source=source,
            symbol_column=symbol_column,
            field_map=field_map,
            sheet_name=sheet_name,
            as_of=as_of,
            source_file_name=source_file_name,
        )
        report["database_records"] = self.repository.count()
        return report

    def report(
        self,
        *,
        limit: int = 1000,
        incomplete_only: bool = False,
        stale_only: bool = False,
    ) -> dict[str, Any]:
        records = []
        all_rows = self.repository.all(limit=max(1, min(int(limit), 5000)))
        complete_count = 0
        stale_count = 0

        for row in all_rows:
            quality = self.quality(row)
            if quality["ready"]:
                complete_count += 1
            if quality["stale"]:
                stale_count += 1
            if incomplete_only and quality["ready"]:
                continue
            if stale_only and not quality["stale"]:
                continue
            records.append(
                {
                    "symbol": row["symbol"],
                    "completeness_pct": quality["completeness_pct"],
                    "ready": quality["ready"],
                    "missing": quality["missing"],
                    "invalid": quality["invalid"],
                    "stale": quality["stale"],
                    "age_days": quality["age_days"],
                    "source": quality["source"],
                    "as_of": quality["as_of"],
                }
            )

        total = len(all_rows)
        average = (
            round(
                sum(item["completeness_pct"] for item in (
                    {
                        "completeness_pct": self.quality(row)["completeness_pct"]
                    }
                    for row in all_rows
                )) / total,
                2,
            )
            if total
            else 0.0
        )
        return {
            "total_records": total,
            "ready_records": complete_count,
            "incomplete_records": total - complete_count,
            "stale_records": stale_count,
            "average_completeness_pct": average,
            "returned": len(records),
            "records": records,
        }

    @classmethod
    def template_frame(cls) -> pd.DataFrame:
        return pd.DataFrame(columns=list(cls.TEMPLATE_COLUMNS))

    @classmethod
    def template_csv(cls) -> bytes:
        buffer = StringIO()
        cls.template_frame().to_csv(buffer, index=False)
        return buffer.getvalue().encode("utf-8-sig")

    @classmethod
    def template_xlsx(cls) -> bytes:
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            cls.template_frame().to_excel(
                writer,
                sheet_name="Fundamentals",
                index=False,
            )
        return buffer.getvalue()


__all__ = ["FundamentalDataManager"]
