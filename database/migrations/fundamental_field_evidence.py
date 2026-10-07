"""Create standardized per-field fundamental evidence history."""


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamental_field_evidence(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            field TEXT NOT NULL,
            value REAL,
            value_status TEXT NOT NULL,
            period_type TEXT,
            period_label TEXT,
            period_start TEXT,
            period_end TEXT,
            methodology TEXT,
            source_type TEXT NOT NULL,
            source TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            as_of TEXT NOT NULL,
            reason TEXT,
            notes TEXT,
            source_file TEXT,
            recorded_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_fundamental_field_evidence_symbol
        ON fundamental_field_evidence(symbol)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_fundamental_field_evidence_symbol_field
        ON fundamental_field_evidence(symbol, field)
        """
    )
