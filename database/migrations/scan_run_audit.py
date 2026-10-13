"""Create persistent scan-run audit storage."""


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_run_audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            scan_type TEXT NOT NULL,
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
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scan_run_audit_created_at
        ON scan_run_audit(created_at DESC)
        """
    )
