"""Add research/report batches to the existing application database."""


def migrate(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS research_batches (
            batch_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            horizon TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            stock_list TEXT NOT NULL,
            requested_symbols INTEGER NOT NULL,
            completed_symbols INTEGER NOT NULL DEFAULT 0,
            phase TEXT NOT NULL DEFAULT 'queued',
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            request_json TEXT NOT NULL,
            report_json TEXT,
            error_code TEXT
        )
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_batches_created "
        "ON research_batches(created_at DESC)"
    )
