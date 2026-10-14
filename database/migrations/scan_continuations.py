"""Persist one-time scan continuation tokens for partial universe runs."""


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_continuations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            parent_run_id TEXT NOT NULL UNIQUE,
            lineage_root_run_id TEXT NOT NULL,
            generation INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            symbols_json TEXT NOT NULL,
            request_json TEXT NOT NULL,
            child_run_id TEXT UNIQUE,
            created_at TEXT NOT NULL,
            claimed_at TEXT,
            consumed_at TEXT,
            updated_at TEXT NOT NULL,
            CHECK(status IN ('pending','active','consumed'))
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scan_continuations_status
        ON scan_continuations(status, created_at DESC)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scan_continuations_lineage
        ON scan_continuations(lineage_root_run_id, generation)
        """
    )
