"""SQLite repository for production scan-run audit records."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from database.database import Database


class ScanRunAuditRepository:
    def __init__(self, db: Database | None = None, db_path: str | None = None):
        self._owns_database = db is None
        self.db = db or Database(db_path)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        for field in (
            "provider_counts_json",
            "error_details_json",
            "metadata_json",
        ):
            raw = result.pop(field, "{}")
            try:
                result[field.removesuffix("_json")] = json.loads(raw or "{}")
            except (TypeError, ValueError):
                result[field.removesuffix("_json")] = {}
        result["full_universe"] = bool(result.get("full_universe"))
        return result

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        run_id = str(record.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("scan audit requires run_id")

        values = (
            run_id,
            str(record.get("scan_type") or "nifty500"),
            str(record.get("started_at") or self._timestamp()),
            str(record.get("finished_at") or self._timestamp()),
            float(record.get("duration_sec") or 0.0),
            int(record.get("requested_symbols") or 0),
            int(record.get("completed_symbols") or 0),
            int(record.get("error_symbols") or 0),
            int(record.get("missing_symbols") or 0),
            int(record.get("enrichment_failures") or 0),
            int(record.get("execution_errors") or 0),
            1 if record.get("full_universe") else 0,
            record.get("source_security_count"),
            record.get("tradable_security_count"),
            json.dumps(record.get("provider_counts") or {}, sort_keys=True),
            int(record.get("fallback_count") or 0),
            int(record.get("nse_resolution_count") or 0),
            json.dumps(record.get("error_details") or {}, sort_keys=True),
            json.dumps(record.get("metadata") or {}, sort_keys=True),
            self._timestamp(),
        )

        self.db.execute(
            """
            INSERT INTO scan_run_audit(
                run_id, scan_type, started_at, finished_at, duration_sec,
                requested_symbols, completed_symbols, error_symbols,
                missing_symbols, enrichment_failures, execution_errors,
                full_universe, source_security_count, tradable_security_count,
                provider_counts_json, fallback_count, nse_resolution_count,
                error_details_json, metadata_json, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
                scan_type=excluded.scan_type,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                duration_sec=excluded.duration_sec,
                requested_symbols=excluded.requested_symbols,
                completed_symbols=excluded.completed_symbols,
                error_symbols=excluded.error_symbols,
                missing_symbols=excluded.missing_symbols,
                enrichment_failures=excluded.enrichment_failures,
                execution_errors=excluded.execution_errors,
                full_universe=excluded.full_universe,
                source_security_count=excluded.source_security_count,
                tradable_security_count=excluded.tradable_security_count,
                provider_counts_json=excluded.provider_counts_json,
                fallback_count=excluded.fallback_count,
                nse_resolution_count=excluded.nse_resolution_count,
                error_details_json=excluded.error_details_json,
                metadata_json=excluded.metadata_json,
                created_at=excluded.created_at
            """,
            values,
        )
        return self.by_run_id(run_id) or dict(record)

    def by_run_id(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM scan_run_audit WHERE run_id=?",
            (str(run_id).strip(),),
        )
        return self._decode(row)

    def latest(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT * FROM scan_run_audit ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        )
        return [self._decode(row) for row in rows]

    def count(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) AS total FROM scan_run_audit"
        )
        return int(row["total"]) if row is not None else 0

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["ScanRunAuditRepository"]
