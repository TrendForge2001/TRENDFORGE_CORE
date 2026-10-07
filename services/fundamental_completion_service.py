"""Generate and safely apply standardized fundamental-completion workbooks."""
from __future__ import annotations

from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from database.repositories.fundamental_field_evidence_repository import (
    FundamentalFieldEvidenceRepository,
)
from database.repositories.fundamental_field_update_repository import (
    FundamentalFieldUpdateRepository,
)
from database.repositories.fundamentals_repository import FundamentalsRepository
from providers.fundamental_mapping import extract_fields
from services.fundamental_data_manager import FundamentalDataManager
from services.fundamental_import_service import FundamentalFileImportService
from services.fundamental_period_standardizer import FundamentalPeriodStandardizer


class FundamentalCompletionService:
    """Complete only missing fields, with explicit period/source evidence."""

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

    def __init__(
        self,
        manager: FundamentalDataManager | None = None,
        audit_repository: FundamentalFieldUpdateRepository | None = None,
        evidence_repository: FundamentalFieldEvidenceRepository | None = None,
        *,
        db_path: str | None = None,
    ) -> None:
        self.manager = manager or FundamentalDataManager(db_path=db_path)
        repository_db = getattr(self.manager.repository, "db", None)
        effective_db_path = db_path or getattr(repository_db, "db_path", None)
        self.audit = audit_repository or FundamentalFieldUpdateRepository(
            db_path=effective_db_path
        )
        self.evidence_repository = (
            evidence_repository
            or FundamentalFieldEvidenceRepository(db_path=effective_db_path)
        )
        self._owns_audit = audit_repository is None
        self._owns_evidence = evidence_repository is None
        self.standardizer = FundamentalPeriodStandardizer()

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
        metadata_columns = self.standardizer.metadata_columns_for(ordered_missing)
        columns = (
            ["Symbol"]
            + [self.FIELD_LABELS[field] for field in ordered_missing]
            + metadata_columns
            + [
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
                output[self.FIELD_LABELS[field]] = None
            for column in metadata_columns:
                output[column] = ""
            output.update(
                {
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
                    "Fill only fields currently missing in SQLite.",
                    "Every supplied value needs a real source and a valid reporting/as-of date.",
                    "ROE must use an annual fiscal-year label such as FY2026.",
                    "EPS Growth must use method 3Y_CAGR with FY start/end exactly three fiscal years apart.",
                    "If 3Y EPS CAGR is not meaningful, leave EPS Growth blank, set EPS Growth Status=N/M, and provide a reason such as NEGATIVE_BASE.",
                    "Promoter Holding and Pledged % are point-in-time values and require their own As Of dates.",
                    "Field-specific Source/Source Ref columns override Completion Source/Source Ref.",
                    "TrendForge will not overwrite already-present fundamentals through this workflow.",
                    "The original baseline Snapshot As Of remains unchanged.",
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
                    48,
                    max(
                        12,
                        max(len(str(cell.value or "")) for cell in column_cells)
                        + 2,
                    ),
                )
                worksheet.column_dimensions[
                    column_cells[0].column_letter
                ].width = width
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
        source: str | None = None,
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
                "evidence_records": 0,
                "completed_records": 0,
                "rows": [],
            }

        symbol_key = FundamentalFileImportService._symbol_column(frame)
        row_reports: list[dict[str, Any]] = []
        unknown_rows: list[dict[str, Any]] = []
        invalid_rows: list[dict[str, Any]] = []
        pending_records: list[dict[str, Any]] = []
        pending_audit: list[dict[str, Any]] = []
        pending_evidence: list[dict[str, Any]] = []
        skipped = 0
        completed_records = 0
        source_file = source_file_name or file_path.name

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
                unknown_rows.append({"row": row_number, "symbol": symbol})
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

            standardized = self.standardizer.validate(
                symbol=symbol,
                payload=payload,
                missing_fields=missing_before,
                numeric_values=accepted,
                fallback_source=source,
                fallback_as_of=as_of,
                source_file=source_file,
            )

            if standardized["errors"]:
                invalid_rows.append(
                    {
                        "row": row_number,
                        "symbol": symbol,
                        "invalid": [],
                        "standardization_errors": standardized["errors"],
                    }
                )
                continue

            evidence_rows = list(standardized["evidence"])
            if not accepted and not evidence_rows:
                skipped += 1
                continue

            candidate = dict(existing)
            for field, value in accepted.items():
                candidate[self.manager.STORAGE_FIELD[field]] = value

            quality_after = self.manager.quality(candidate)
            if quality_after["invalid"]:
                invalid_rows.append(
                    {
                        "row": row_number,
                        "symbol": symbol,
                        "invalid": quality_after["invalid"],
                        "standardization_errors": [],
                    }
                )
                continue

            if accepted:
                record: dict[str, Any] = {"symbol": symbol}
                for field, value in accepted.items():
                    record[self.manager.STORAGE_FIELD[field]] = value
                pending_records.append(record)

                evidence_by_field = {
                    item["field"]: item for item in evidence_rows
                }
                for field, value in accepted.items():
                    item = evidence_by_field.get(field)
                    if item is None:
                        continue
                    pending_audit.append(
                        {
                            "symbol": symbol,
                            "field": field,
                            "value": value,
                            "source": item["source"],
                            "source_file": source_file,
                            "as_of": item["as_of"],
                        }
                    )

            pending_evidence.extend(evidence_rows)

            if quality_after["ready"]:
                completed_records += 1

            row_reports.append(
                {
                    "row": row_number,
                    "symbol": symbol,
                    "before_completeness_pct": quality_before[
                        "completeness_pct"
                    ],
                    "after_completeness_pct": quality_after[
                        "completeness_pct"
                    ],
                    "filled_fields": list(accepted),
                    "non_numeric_fields": standardized[
                        "non_numeric_fields"
                    ],
                    "remaining_missing": quality_after["missing"],
                    "ready_after": quality_after["ready"],
                    "snapshot_as_of_preserved": existing.get("as_of"),
                    "evidence": evidence_rows,
                }
            )

        applied_records = 0
        applied_fields = 0
        evidence_records = 0
        if apply:
            for record in pending_records:
                self.manager.repository.save(record)
            applied_records = len(pending_records)
            applied_fields = self.audit.add_many(pending_audit)
            evidence_records = self.evidence_repository.add_many(
                pending_evidence
            )

        return {
            "status": "applied" if apply else "preview",
            "mode": "apply" if apply else "preview",
            "file": str(file_path),
            "source_file": source_file,
            "rows_read": int(len(frame)),
            "eligible": len(row_reports),
            "unknown_symbols": len(unknown_rows),
            "invalid": len(invalid_rows),
            "skipped": skipped,
            "applied_records": applied_records,
            "applied_fields": applied_fields,
            "evidence_records": evidence_records,
            "completed_records": completed_records,
            "database_records": self.manager.repository.count(),
            "rows": row_reports,
            "unknown_rows": unknown_rows,
            "invalid_rows": invalid_rows,
        }

    def history(self, symbol: str, limit: int = 200) -> list[dict[str, Any]]:
        return self.audit.by_symbol(symbol, limit=limit)

    def evidence(
        self,
        symbol: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        return {
            "symbol": FundamentalsRepository.normalize_symbol(symbol),
            "latest_by_field": self.evidence_repository.latest_by_field(symbol),
            "history": self.evidence_repository.by_symbol(symbol, limit=limit),
        }

    def close(self) -> None:
        if self._owns_audit:
            self.audit.close()
        if self._owns_evidence:
            self.evidence_repository.close()


__all__ = ["FundamentalCompletionService"]
