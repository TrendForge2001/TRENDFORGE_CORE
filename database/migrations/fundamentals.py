"""Create and upgrade the canonical fundamentals table."""


COLUMNS = {
    "eps_growth": "REAL",
    "pledged": "REAL",
    "source": "TEXT",
    "source_file": "TEXT",
    "as_of": "TEXT",
    "imported_at": "TEXT",
}


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals(
            symbol TEXT PRIMARY KEY,
            market_cap REAL,
            pe REAL,
            pb REAL,
            eps REAL,
            roe REAL,
            roce REAL,
            debt_to_equity REAL,
            sales_growth REAL,
            profit_growth REAL,
            eps_growth REAL,
            promoter_holding REAL,
            pledged REAL,
            fii_holding REAL,
            dii_holding REAL,
            dividend_yield REAL,
            current_ratio REAL,
            quick_ratio REAL,
            book_value REAL,
            face_value REAL,
            sector TEXT,
            industry TEXT,
            source TEXT,
            source_file TEXT,
            as_of TEXT,
            imported_at TEXT,
            updated_at TEXT
        )
        """
    )

    existing = {
        row["name"]
        for row in db.fetchall("PRAGMA table_info(fundamentals)")
    }
    for name, column_type in COLUMNS.items():
        if name not in existing:
            db.execute(
                f"ALTER TABLE fundamentals ADD COLUMN {name} {column_type}"
            )
