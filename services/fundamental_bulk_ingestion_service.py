"""R69.5 staged, resumable fundamental bulk-ingestion orchestration."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

import pandas as pd

from database.repositories.fundamental_bulk_run_repository import (
    FundamentalBulkRunRepository,
)
from database.repositories.fundamentals_repository import FundamentalsRepository
from services.fundamental_completion_service import FundamentalCompletionService
from services.fundamental_coverage_service import FundamentalCoverageService
from services.fundamental_import_service import FundamentalFileImportService


class FundamentalBulkIngestionService:
    """Stage verified completion files into SQLite without weakening gates."""

    VERSION = "R69.5"
    STAGE_SIZES = (25, 50, 100, 250, 500)

    def __init__(
        self,
        *,
        completion: FundamentalCompletionService,
        coverage: FundamentalCoverageService,
        repository: FundamentalBulkRunRepository | None = None,
    ) -> None:
        if completion is None:
            raise ValueError("completion service is required")
        if coverage is None:
            raise ValueError("coverage service is required")
        self.completion = completion
        self.coverage = coverage
        manager_repository = getattr(
            getattr(completion, "manager", None),
            "repository",
            None,
        )
        repository_db = getattr(manager_repository, "db", None)
        self.repository = repository or FundamentalBulkRunRepository(
            db=repository_db
        )
        self._owns_repository = repository is None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _stage_size(cls, value: int) -> int:
        stage = int(value)
        if stage not in cls.STAGE_SIZES:
            raise ValueError(
                "stage_size must be one of "
                + ", ".join(str(item) for item in cls.STAGE_SIZES)
            )
        return stage

    @staticmethod
    def _coverage_summary(report: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "tradable_symbols",
            "database_records",
            "database_coverage_pct",
            "missing_database_records",
            "scoring_ready_records",
            "scoring_readiness_pct",
            "scanner_ready_records",
            "scanner_readiness_pct",
            "quality_pass_records",
            "scanner_quality_pass_records",
            "stale_records",
        )
        return {
            key: report.get(key)
            for key in keys
        }

    @classmethod
    def _coverage_delta(
        cls,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> dict[str, Any]:
        before = before or {}
        after = after or {}
        numeric_keys = (
            "database_records",
            "missing_database_records",
            "scoring_ready_records",
            "scanner_ready_records",
            "quality_pass_records",
            "scanner_quality_pass_records",
            "stale_records",
        )
        delta: dict[str, Any] = {}
        for key in numeric_keys:
            old = before.get(key)
            new = after.get(key)
            if isinstance(old, (int, float)) and isinstance(
                new,
                (int, float),
            ):
                delta[key] = new - old
        for key in (
            "database_coverage_pct",
            "scoring_readiness_pct",
            "scanner_readiness_pct",
        ):
            old = before.get(key)
            new = after.get(key)
            if isinstance(old, (int, float)) and isinstance(
                new,
                (int, float),
            ):
                delta[key] = round(float(new) - float(old), 4)
        return delta

    @staticmethod
    def _normalized_symbols(
        frame: pd.DataFrame,
        symbol_key: str,
    ) -> list[str]:
        values: list[str] = []
        for raw in frame[symbol_key].tolist():
            symbol = FundamentalsRepository.normalize_symbol(raw)
            if symbol and symbol not in {"NAN", "NONE"}:
                values.append(symbol)
        return values

    @classmethod
    def _duplicate_symbols(
        cls,
        frame: pd.DataFrame,
        symbol_key: str,
    ) -> list[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for symbol in cls._normalized_symbols(frame, symbol_key):
            if symbol in seen:
                duplicates.add(symbol)
            seen.add(symbol)
        return sorted(duplicates)

    def readiness(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "status": "ready",
            "stage_sizes": list(self.STAGE_SIZES),
            "preview_required_before_apply": True,
            "unknown_symbols_allowed": False,
            "invalid_rows_allowed": False,
            "duplicate_symbols_allowed": False,
            "overwrite_attempts_allowed": False,
            "evidence_failures_allowed": False,
            "live_broker_orders_allowed": False,
        }

    def _load(
        self,
        path: Path,
        *,
        sheet_name: str | int | None,
    ) -> tuple[pd.DataFrame, str]:
        frame = self.completion._load_frame(
            path,
            sheet_name=sheet_name,
        )
        symbol_key = FundamentalFileImportService._symbol_column(frame)
        return frame, symbol_key

    def _stage_preview(
        self,
        *,
        frame: pd.DataFrame,
        start: int,
        end: int,
        source: str | None,
        as_of: str | None,
        source_file_name: str,
    ) -> dict[str, Any]:
        stage_frame = frame.iloc[start:end].copy()
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            newline="",
            delete=False,
            encoding="utf-8",
        ) as handle:
            temp_path = Path(handle.name)
            stage_frame.to_csv(handle, index=False)

        try:
            return self.completion.process_file(
                temp_path,
                apply=False,
                source=source,
                as_of=as_of,
                sheet_name=0,
                source_file_name=source_file_name,
            )
        finally:
            temp_path.unlink(missing_ok=True)

    def _stage_apply(
        self,
        *,
        frame: pd.DataFrame,
        start: int,
        end: int,
        source: str | None,
        as_of: str | None,
        source_file_name: str,
    ) -> dict[str, Any]:
        stage_frame = frame.iloc[start:end].copy()
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            newline="",
            delete=False,
            encoding="utf-8",
        ) as handle:
            temp_path = Path(handle.name)
            stage_frame.to_csv(handle, index=False)

        try:
            return self.completion.process_file(
                temp_path,
                apply=True,
                source=source,
                as_of=as_of,
                sheet_name=0,
                source_file_name=source_file_name,
            )
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def _gate(
        preview: dict[str, Any],
        *,
        duplicate_symbols: list[str],
    ) -> dict[str, Any]:
        unknown = int(preview.get("unknown_symbols") or 0)
        invalid = int(preview.get("invalid") or 0)
        overwrite_attempts = int(
            preview.get("overwrite_attempts") or 0
        )
        evidence_failures = int(
            preview.get("evidence_failures") or 0
        )
        duplicates = len(duplicate_symbols)
        reasons: list[str] = []
        if unknown:
            reasons.append("unknown_symbols")
        if invalid:
            reasons.append("invalid_rows")
        if duplicates:
            reasons.append("duplicate_symbols")
        if overwrite_attempts:
            reasons.append("overwrite_attempts")
        if evidence_failures:
            reasons.append("evidence_failures")
        return {
            "pass": not reasons,
            "reasons": reasons,
            "unknown_symbols": unknown,
            "invalid_rows": invalid,
            "duplicate_symbols": duplicates,
            "duplicate_symbol_list": duplicate_symbols,
            "overwrite_attempts": overwrite_attempts,
            "evidence_failures": evidence_failures,
            "eligible_rows": int(preview.get("eligible") or 0),
            "skipped_rows": int(preview.get("skipped") or 0),
            "projected_completed_records": int(
                preview.get("completed_records") or 0
            ),
        }

    @classmethod
    def _next_stage_size(cls, current: int) -> int:
        try:
            index = cls.STAGE_SIZES.index(int(current))
        except ValueError:
            return cls.STAGE_SIZES[0]
        if index >= len(cls.STAGE_SIZES) - 1:
            return cls.STAGE_SIZES[-1]
        return cls.STAGE_SIZES[index + 1]

    def process_file(
        self,
        path: str | Path,
        *,
        run_id: str | None = None,
        stage_size: int = 25,
        apply: bool = False,
        source: str | None = None,
        as_of: str | None = None,
        sheet_name: str | int | None = "Completion",
        source_file_name: str | None = None,
    ) -> dict[str, Any]:
        file_path = Path(path).expanduser()
        if not file_path.is_file():
            raise FileNotFoundError(
                f"Fundamental bulk file not found: {file_path}"
            )
        stage_size = self._stage_size(stage_size)
        frame, symbol_key = self._load(
            file_path,
            sheet_name=sheet_name,
        )
        if frame.empty:
            raise ValueError("Fundamental bulk file is empty")

        total_rows = int(len(frame))
        file_sha = self._sha256(file_path)
        source_file = source_file_name or file_path.name
        bulk_run_id = str(run_id or f"fund-bulk-{uuid4()}").strip()
        if not bulk_run_id:
            raise ValueError("run_id is required")

        duplicate_symbols = self._duplicate_symbols(frame, symbol_key)
        record = self.repository.get(bulk_run_id)
        if record is None:
            coverage_before_full = self.coverage.report(limit=5000)
            coverage_before = self._coverage_summary(
                coverage_before_full
            )
            record = self.repository.create(
                run_id=bulk_run_id,
                file_sha256=file_sha,
                source_file=source_file,
                total_rows=total_rows,
                coverage_before=coverage_before,
            )
        else:
            if record.get("file_sha256") != file_sha:
                raise ValueError(
                    "run_id belongs to a different bulk file SHA256"
                )
            if int(record.get("total_rows") or 0) != total_rows:
                raise ValueError(
                    "run_id bulk file row count changed"
                )

        if record.get("status") == "completed":
            return {
                "version": self.VERSION,
                "run": record,
                "status": "completed",
                "message": "Bulk ingestion run is already completed.",
            }

        start = int(record.get("next_offset") or 0)
        end = min(start + stage_size, total_rows)
        if start >= total_rows:
            latest = self.repository.advance(
                bulk_run_id,
                next_offset=total_rows,
                aggregate=dict(record.get("aggregate") or {}),
                coverage_after=dict(
                    record.get("coverage_after")
                    or record.get("coverage_before")
                    or {}
                ),
                completed=True,
            )
            return {
                "version": self.VERSION,
                "run": latest,
                "status": "completed",
            }

        preview = self._stage_preview(
            frame=frame,
            start=start,
            end=end,
            source=source,
            as_of=as_of,
            source_file_name=source_file,
        )
        gate = self._gate(
            preview,
            duplicate_symbols=duplicate_symbols,
        )
        preview_payload = {
            "range": {
                "start": start,
                "end": end,
                "row_count": end - start,
                "stage_size": stage_size,
            },
            "gate": gate,
            "report": preview,
        }

        prior_preview_matches = (
            record.get("last_preview_start") == start
            and record.get("last_preview_end") == end
            and record.get("last_preview_stage_size") == stage_size
            and bool(record.get("last_preview_gate_pass"))
        )

        saved = self.repository.save_preview(
            bulk_run_id,
            start=start,
            end=end,
            stage_size=stage_size,
            gate_pass=bool(gate["pass"]),
            preview=preview_payload,
            blocked=not bool(gate["pass"]),
        )

        if not apply:
            return {
                "version": self.VERSION,
                "status": (
                    "preview_ready"
                    if gate["pass"]
                    else "preview_blocked"
                ),
                "run_id": bulk_run_id,
                "file_sha256": file_sha,
                "source_file": source_file,
                "total_rows": total_rows,
                "next_offset": start,
                "stage": preview_payload,
                "run": saved,
                "recommended_next_stage_size": (
                    self._next_stage_size(stage_size)
                ),
            }

        if not gate["pass"]:
            return {
                "version": self.VERSION,
                "status": "apply_blocked",
                "run_id": bulk_run_id,
                "stage": preview_payload,
                "run": saved,
            }

        if not prior_preview_matches:
            return {
                "version": self.VERSION,
                "status": "preview_required",
                "run_id": bulk_run_id,
                "message": (
                    "A clean persisted preview of this exact stage is "
                    "required before apply. Re-submit the same run_id, "
                    "file and stage_size with apply=true."
                ),
                "stage": preview_payload,
                "run": saved,
            }

        coverage_before_stage = dict(
            record.get("coverage_after")
            or record.get("coverage_before")
            or {}
        )
        applied = self._stage_apply(
            frame=frame,
            start=start,
            end=end,
            source=source,
            as_of=as_of,
            source_file_name=source_file,
        )
        coverage_after_full = self.coverage.report(limit=5000)
        coverage_after = self._coverage_summary(
            coverage_after_full
        )
        delta = self._coverage_delta(
            coverage_before_stage,
            coverage_after,
        )

        aggregate = dict(record.get("aggregate") or {})
        increments = {
            "processed_rows": end - start,
            "applied_records": int(
                applied.get("applied_records") or 0
            ),
            "applied_fields": int(
                applied.get("applied_fields") or 0
            ),
            "evidence_records": int(
                applied.get("evidence_records") or 0
            ),
            "completed_records": int(
                applied.get("completed_records") or 0
            ),
            "invalid": int(applied.get("invalid") or 0),
            "unknown_symbols": int(
                applied.get("unknown_symbols") or 0
            ),
            "duplicates": len(duplicate_symbols),
            "overwrite_attempts": int(
                applied.get("overwrite_attempts") or 0
            ),
            "evidence_failures": int(
                applied.get("evidence_failures") or 0
            ),
            "stages_applied": 1,
        }
        for key, value in increments.items():
            aggregate[key] = int(aggregate.get(key) or 0) + int(value)

        completed = end >= total_rows
        latest = self.repository.advance(
            bulk_run_id,
            next_offset=end,
            aggregate=aggregate,
            coverage_after=coverage_after,
            completed=completed,
        )
        return {
            "version": self.VERSION,
            "status": "completed" if completed else "stage_applied",
            "run_id": bulk_run_id,
            "file_sha256": file_sha,
            "source_file": source_file,
            "total_rows": total_rows,
            "stage": {
                **preview_payload,
                "apply_report": applied,
                "coverage_before": coverage_before_stage,
                "coverage_after": coverage_after,
                "coverage_delta": delta,
            },
            "run": latest,
            "remaining_rows": max(0, total_rows - end),
            "recommended_next_stage_size": (
                self._next_stage_size(stage_size)
            ),
        }

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self.repository.get(run_id)

    def history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.repository.list(limit=limit)

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()


__all__ = ["FundamentalBulkIngestionService"]
