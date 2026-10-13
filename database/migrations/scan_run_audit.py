"""Create and evolve immutable scan-run audit storage."""


def _columns(db):
    return {
        str(row["name"])
        for row in db.fetchall("PRAGMA table_info(scan_run_audit)")
    }


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_run_audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            scan_type TEXT NOT NULL,
            outcome TEXT NOT NULL DEFAULT 'completed',
            http_status INTEGER NOT NULL DEFAULT 200,
            failure_stage TEXT,
            failure_message TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            duration_sec REAL NOT NULL,
            requested_symbols INTEGER NOT NULL,
            completed_symbols INTEGER NOT NULL,
            error_symbols INTEGER NOT NULL,
            missing_symbols INTEGER NOT NULL,
            enrichment_failures INTEGER NOT NULL,
            execution_errors INTEGER NOT NULL,
            full_universe INTEGER NOT NULL DEFAULT 0,
            source_security_count INTEGER,
            tradable_security_count INTEGER,
            provider_counts_json TEXT NOT NULL,
            fallback_count INTEGER NOT NULL DEFAULT 0,
            nse_resolution_count INTEGER NOT NULL DEFAULT 0,
            error_details_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    columns = _columns(db)
    additions = (
        (
            "outcome",
            "ALTER TABLE scan_run_audit "
            "ADD COLUMN outcome TEXT NOT NULL DEFAULT 'completed'",
        ),
        (
            "http_status",
            "ALTER TABLE scan_run_audit "
            "ADD COLUMN http_status INTEGER NOT NULL DEFAULT 200",
        ),
        (
            "failure_stage",
            "ALTER TABLE scan_run_audit ADD COLUMN failure_stage TEXT",
        ),
        (
            "failure_message",
            "ALTER TABLE scan_run_audit ADD COLUMN failure_message TEXT",
        ),
    )
    for name, statement in additions:
        if name not in columns:
            db.execute(statement)

    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scan_run_audit_created_at
        ON scan_run_audit(created_at DESC)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scan_run_audit_outcome
        ON scan_run_audit(outcome, created_at DESC)
        """
    )
