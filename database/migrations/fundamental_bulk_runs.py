"""Persist resumable R69.5 fundamental bulk-ingestion runs."""
from __future__ import annotations


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamental_bulk_runs(
            run_id TEXT PRIMARY KEY,
            file_sha256 TEXT NOT NULL,
            source_file TEXT NOT NULL,
            total_rows INTEGER NOT NULL,
            next_offset INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'created',
            last_preview_start INTEGER,
            last_preview_end INTEGER,
            last_preview_stage_size INTEGER,
            last_preview_gate_pass INTEGER NOT NULL DEFAULT 0,
            last_preview_json TEXT,
            aggregate_json TEXT,
            coverage_before_json TEXT,
            coverage_after_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            CHECK(status IN (
                'created',
                'previewed',
                'in_progress',
                'completed',
                'blocked',
                'failed'
            ))
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_fundamental_bulk_runs_status
        ON fundamental_bulk_runs(status, updated_at DESC)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_fundamental_bulk_runs_created
        ON fundamental_bulk_runs(created_at DESC)
        """
    )


__all__ = ["migrate"]
