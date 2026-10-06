"""Generate and safely apply fundamental-completion workbooks."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from database.repositories.fundamental_field_update_repository import (
    FundamentalFieldUpdateRepository,
)
from database.repositories.fundamentals_repository import FundamentalsRepository
from providers.fundamental_mapping import extract_fields
from services.fundamental_data_manager import FundamentalDataManager
from services.fundamental_import_service import FundamentalFileImportService


class FundamentalCompletionService:
    """Complete only fields that are currently missing in SQLite."""

    FIELD_LABELS = {
        "roce": "ROCE",
        "roe": "ROE",
        "sales_growth": "Sales Growth",
        "profit_growth": "Profit Growth",
        "eps_growth": "EPS Growth",
        "debt_equity": "Debt/Equity",
        "promoter_holding": "Promoter Holding",
        "pledged": "Pledged %",
    }
    SOURCE_ALIASES = (
        "completion source",
        "source",
        "data source",
    )
    AS_OF_ALIASES = (
        "completion as of",
        "as of",
        "as_of",
        "completion date",
    )

    def __init__(
        self,
        manager: FundamentalDataManager | None = None,
        audit_repository: FundamentalFieldUpdateRepository | None = None,
        *,
        db_path: str | None = None,
    ) -> None:
        self.manager = manager or FundamentalDataManager(db_path=db_path)
        repository_db = getattr(self.manager.repository, "db", None)
        effective_db_path = db_path or getattr(repository_db, "db_path", None)
        self.audit = audit_repository or FundamentalFieldUpdateRepository(
            db_path=effective_db_path
        )
        self._owns_audit = audit_repository is None

    @staticmethod
    def _normalize_column(value: Any) -> str:
        return " ".join(
            str(value or "")
            .strip()
            .lower()
            .replace("_", " ")
            .replace("%", " %")
            .split()
        )

    @classmethod
    def _optional_column(
        cls,
        frame: pd.DataFrame,
        aliases: tuple[str, ...],
    ) -> str | None:
        normalized = {
            cls._normalize_column(column): str(column)
            for column in frame.columns
        }
        for alias in aliases:
            matched = normalized.get(cls._normalize_column(alias))
            if matched:
                return matched
        return None

    def completion_frame(
        self,
        *,
        symbols: list[str] | tuple[str, ...] | None = None,
        limit: int = 5000,
    ) -> pd.DataFrame:
        selected = (
            {
                FundamentalsRepository.normalize_symbol(symbol)
                for symbol in symbols
                if FundamentalsRepository.normalize_symbol(symbol)
            }
            if symbols
            else None
        )

        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        missing_union: set[str] = set()
        for row in self.manager.repository.all(
            limit=max(1, min(int(limit), 5000))
        ):
            if selected is not None and row["symbol"] not in selected:
                continue
            quality = self.manager.quality(row)
            missing = list(quality["missing"])
            if not missing:
                continue
            candidates.append((row, quality))
            missing_union.update(missing)

        ordered_missing = [
            field
            for field in self.manager.REQUIRED_FIELDS
            if field in missing_union
        ]
        columns = (
            ["Symbol"]
            + [self.FIELD_LABELS[field] for field in ordered_missing]
            + [
                "Completion Source",
                "Completion As Of",
                "Current Completeness %",
                "Missing Fields",
                "Snapshot As Of",
                "Baseline Source",
            ]
        )

        rows: list[dict[str, Any]] = []
        for row, quality in candidates:
            output: dict[str, Any] = {"Symbol": row["symbol"]}
            for field in ordered_missing:
                # Completion cells remain blank. Import logic only accepts a
                # value if that field is still missing at apply time.
                output[self.FIELD_LABELS[field]] = None
            output.update(
                {
                    "Completion Source": "",
                    "Completion As Of": "",
                    "Current Completeness %": quality["completeness_pct"],
                    "Missing Fields": ", ".join(quality["missing"]),
                    "Snapshot As Of": row.get("as_of") or "",
                    "Baseline Source": row.get("source") or "",
                }
            )
            rows.append(output)

        return pd.DataFrame(rows, columns=columns)

    def completion_csv(
        self,
        *,
        symbols: list[str] | tuple[str, ...] | None = None,
        limit: int = 5000,
    ) -> bytes:
        buffer = StringIO()
        self.completion_frame(symbols=symbols, limit=limit).to_csv(
            buffer,
            index=False,
        )
        return buffer.getvalue().encode("utf-8-sig")

    def completion_xlsx(
        self,
        *,
        symbols: list[str] | tuple[str, ...] | None = None,
        limit: int = 5000,
    ) -> bytes:
        frame = self.completion_frame(symbols=symbols, limit=limit)
        instructions = pd.DataFrame(
            {
                "Instructions": [
                    "Fill only blank fundamental cells.",
                    "Do not use this workbook to change fields already present in SQLite.",
                    "TrendForge ignores values for fields that are no longer missing at import time.",
                    "Completion Source and Completion As Of describe the newly supplied values only.",
                    "The original fundamentals Snapshot As Of is preserved to avoid falsely refreshing older baseline data.",
                    "Preview the workbook before applying it.",
                ]
            }
        )
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="Completion", index=False)
            instructions.to_excel(writer, sheet_name="Instructions", index=False)
            worksheet = writer.book["Completion"]
            worksheet.freeze_panes = "A2"
            for column_cells in worksheet.columns:
                width = min(
                    45,
                    max(
                        12,
                        max(
                            len(str(cell.value or ""))
                            for cell in column_cells
                        ) + 2,
                    ),
                )
                worksheet.column_dimensions[column_cells[0].column_letter].width = width
        return buffer.getvalue()

    @staticmethod
    def _load_frame(
        path: Path,
        *,
        sheet_name: str | int | None = "Completion",
    ) -> pd.DataFrame:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path)
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            requested = sheet_name
            try:
                return pd.read_excel(path, sheet_name=requested)
            except ValueError:
                if requested == "Completion":
                    return pd.read_excel(path, sheet_name=0)
                raise
        raise ValueError("Completion file must be CSV, XLSX or XLSM")

    def process_file(
        self,
        path: str | Path,
        *,
        apply: bool = False,
        source: str = "manual_completion",
        as_of: str | None = None,
        sheet_name: str | int | None = "Completion",
        source_file_name: str | None = None,
    ) -> dict[str, Any]:
        file_path = Path(path).expanduser()
        if not file_path.is_file():
            raise FileNotFoundError(
                f"Fundamental completion file not found: {file_path}"
            )

        frame = self._load_frame(file_path, sheet_name=sheet_name)
        if frame.empty:
            return {
                "status": "empty",
                "mode": "apply" if apply else "preview",
                "rows_read": 0,
                "eligible": 0,
                "unknown_symbols": 0,
                "invalid": 0,
                "skipped": 0,
                "applied_records": 0,
                "applied_fields": 0,
                "completed_records": 0,
                "rows": [],
            }

        symbol_key = FundamentalFileImportService._symbol_column(frame)
        source_key = self._optional_column(frame, self.SOURCE_ALIASES)
        as_of_key = self._optional_column(frame, self.AS_OF_ALIASES)

        row_reports: list[dict[str, Any]] = []
        unknown_rows: list[dict[str, Any]] = []
        invalid_rows: list[dict[str, Any]] = []
        pending_records: list[dict[str, Any]] = []
        pending_audit: list[dict[str, Any]] = []
        skipped = 0
        completed_records = 0

        for row_number, (_, series) in enumerate(frame.iterrows(), start=2):
            payload = series.to_dict()
            symbol = FundamentalsRepository.normalize_symbol(
                payload.get(symbol_key)
            )
            if not symbol or symbol in {"NAN", "NONE"}:
                skipped += 1
                continue

            existing = self.manager.repository.by_symbol(symbol)
            if existing is None:
                unknown_rows.append(
                    {"row": row_number, "symbol": symbol}
                )
                continue

            quality_before = self.manager.quality(existing)
            missing_before = list(quality_before["missing"])
            if not missing_before:
                skipped += 1
                continue

            parsed = extract_fields(payload)
            accepted = {
                field: parsed[field]
                for field in missing_before
                if field in parsed
            }
            if not accepted:
                skipped += 1
                continue

            candidate = dict(existing)
            for field, value in accepted.items():
                storage = self.manager.STORAGE_FIELD[field]
                candidate[storage] = value

            quality_after = self.manager.quality(candidate)
            if quality_after["invalid"]:
                invalid_rows.append(
                    {
                        "row": row_number,
                        "symbol": symbol,
                        "invalid": quality_after["invalid"],
                    }
                )
                continue

            row_source = payload.get(source_key) if source_key else None
            row_as_of = payload.get(as_of_key) if as_of_key else None
            if pd.isna(row_source):
                row_source = None
            if pd.isna(row_as_of):
                row_as_of = None
            completion_source = str(row_source or source or "manual_completion")
            completion_as_of = (
                str(row_as_of)
                if row_as_of not in {None, ""}
                else as_of
            )

            record: dict[str, Any] = {"symbol": symbol}
            for field, value in accepted.items():
                record[self.manager.STORAGE_FIELD[field]] = value
            pending_records.append(record)

            for field, value in accepted.items():
                pending_audit.append(
                    {
                        "symbol": symbol,
                        "field": field,
                        "value": value,
                        "source": completion_source,
                        "source_file": source_file_name or file_path.name,
                        "as_of": completion_as_of,
                    }
                )

            if quality_after["ready"]:
                completed_records += 1
            row_reports.append(
                {
                    "row": row_number,
                    "symbol": symbol,
                    "before_completeness_pct": quality_before["completeness_pct"],
                    "after_completeness_pct": quality_after["completeness_pct"],
                    "filled_fields": list(accepted),
                    "remaining_missing": quality_after["missing"],
                    "ready_after": quality_after["ready"],
                    "snapshot_as_of_preserved": existing.get("as_of"),
                    "completion_source": completion_source,
                    "completion_as_of": completion_as_of,
                }
            )

        applied_records = 0
        applied_fields = 0
        if apply and pending_records:
            for record in pending_records:
                self.manager.repository.save(record)
            applied_records = len(pending_records)
            applied_fields = self.audit.add_many(pending_audit)

        return {
            "status": "applied" if apply else "preview",
            "mode": "apply" if apply else "preview",
            "file": str(file_path),
            "source_file": source_file_name or file_path.name,
            "rows_read": int(len(frame)),
            "eligible": len(row_reports),
            "unknown_symbols": len(unknown_rows),
            "invalid": len(invalid_rows),
            "skipped": skipped,
            "applied_records": applied_records,
            "applied_fields": applied_fields,
            "completed_records": completed_records,
            "database_records": self.manager.repository.count(),
            "rows": row_reports,
            "unknown_rows": unknown_rows,
            "invalid_rows": invalid_rows,
        }

    def history(self, symbol: str, limit: int = 200) -> list[dict[str, Any]]:
        return self.audit.by_symbol(symbol, limit=limit)

    def close(self) -> None:
        if self._owns_audit:
            self.audit.close()


__all__ = ["FundamentalCompletionService"]
