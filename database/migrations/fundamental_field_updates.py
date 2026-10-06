"""Create per-field audit history for fundamental completions."""


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamental_field_updates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            field TEXT NOT NULL,
            value REAL NOT NULL,
            source TEXT,
            source_file TEXT,
            as_of TEXT,
            imported_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_fundamental_field_updates_symbol
        ON fundamental_field_updates(symbol)
        """
    )
