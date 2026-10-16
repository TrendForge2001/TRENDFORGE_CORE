"""Repository for resumable fundamental bulk-ingestion runs."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any

from database.database import Database


class FundamentalBulkRunRepository:
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
        item = dict(row)
        for source, target, default in (
            ("last_preview_json", "last_preview", None),
            ("aggregate_json", "aggregate", {}),
            ("coverage_before_json", "coverage_before", None),
            ("coverage_after_json", "coverage_after", None),
        ):
            raw = item.pop(source, None)
            try:
                item[target] = json.loads(raw) if raw else default
            except (TypeError, ValueError):
                item[target] = default
        item["next_offset"] = int(item.get("next_offset") or 0)
        item["total_rows"] = int(item.get("total_rows") or 0)
        item["last_preview_gate_pass"] = bool(
            item.get("last_preview_gate_pass")
        )
        for key in (
            "last_preview_start",
            "last_preview_end",
            "last_preview_stage_size",
        ):
            if item.get(key) is not None:
                item[key] = int(item[key])
        return item

    def get(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM fundamental_bulk_runs WHERE run_id=?",
            (str(run_id or "").strip(),),
        )
        return self._decode(row)

    def create(
        self,
        *,
        run_id: str,
        file_sha256: str,
        source_file: str,
        total_rows: int,
        coverage_before: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = str(run_id or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        now = self._timestamp()
        try:
            self.db.execute(
                """
                INSERT INTO fundamental_bulk_runs(
                    run_id, file_sha256, source_file, total_rows,
                    next_offset, status,
                    last_preview_start, last_preview_end,
                    last_preview_stage_size, last_preview_gate_pass,
                    last_preview_json, aggregate_json,
                    coverage_before_json, coverage_after_json,
                    created_at, updated_at, completed_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    str(file_sha256),
                    str(source_file),
                    max(0, int(total_rows)),
                    0,
                    "created",
                    None,
                    None,
                    None,
                    0,
                    None,
                    json.dumps(
                        {
                            "processed_rows": 0,
                            "applied_records": 0,
                            "applied_fields": 0,
                            "evidence_records": 0,
                            "completed_records": 0,
                            "invalid": 0,
                            "unknown_symbols": 0,
                            "duplicates": 0,
                            "overwrite_attempts": 0,
                            "evidence_failures": 0,
                            "stages_applied": 0,
                        },
                        sort_keys=True,
                    ),
                    json.dumps(coverage_before or {}, sort_keys=True),
                    json.dumps(coverage_before or {}, sort_keys=True),
                    now,
                    now,
                    None,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"bulk run already exists: {run_id}") from exc
        result = self.get(run_id)
        if result is None:
            raise RuntimeError("bulk run could not be persisted")
        return result

    def save_preview(
        self,
        run_id: str,
        *,
        start: int,
        end: int,
        stage_size: int,
        gate_pass: bool,
        preview: dict[str, Any],
        blocked: bool,
    ) -> dict[str, Any]:
        now = self._timestamp()
        self.db.execute(
            """
            UPDATE fundamental_bulk_runs
            SET status=?,
                last_preview_start=?,
                last_preview_end=?,
                last_preview_stage_size=?,
                last_preview_gate_pass=?,
                last_preview_json=?,
                updated_at=?
            WHERE run_id=?
            """,
            (
                "blocked" if blocked else "previewed",
                int(start),
                int(end),
                int(stage_size),
                1 if gate_pass else 0,
                json.dumps(preview or {}, sort_keys=True),
                now,
                str(run_id or "").strip(),
            ),
        )
        result = self.get(run_id)
        if result is None:
            raise LookupError("bulk run not found")
        return result

    def advance(
        self,
        run_id: str,
        *,
        next_offset: int,
        aggregate: dict[str, Any],
        coverage_after: dict[str, Any],
        completed: bool,
    ) -> dict[str, Any]:
        now = self._timestamp()
        self.db.execute(
            """
            UPDATE fundamental_bulk_runs
            SET next_offset=?,
                status=?,
                aggregate_json=?,
                coverage_after_json=?,
                last_preview_start=NULL,
                last_preview_end=NULL,
                last_preview_stage_size=NULL,
                last_preview_gate_pass=0,
                last_preview_json=NULL,
                updated_at=?,
                completed_at=?
            WHERE run_id=?
            """,
            (
                int(next_offset),
                "completed" if completed else "in_progress",
                json.dumps(aggregate or {}, sort_keys=True),
                json.dumps(coverage_after or {}, sort_keys=True),
                now,
                now if completed else None,
                str(run_id or "").strip(),
            ),
        )
        result = self.get(run_id)
        if result is None:
            raise LookupError("bulk run not found")
        return result

    def fail(
        self,
        run_id: str,
        *,
        message: str,
    ) -> dict[str, Any] | None:
        record = self.get(run_id)
        if record is None:
            return None
        aggregate = dict(record.get("aggregate") or {})
        aggregate["last_error"] = str(message)
        now = self._timestamp()
        self.db.execute(
            """
            UPDATE fundamental_bulk_runs
            SET status='failed',
                aggregate_json=?,
                updated_at=?
            WHERE run_id=?
            """,
            (
                json.dumps(aggregate, sort_keys=True),
                now,
                str(run_id or "").strip(),
            ),
        )
        return self.get(run_id)

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT *
            FROM fundamental_bulk_runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        )
        return [self._decode(row) for row in rows]

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["FundamentalBulkRunRepository"]
