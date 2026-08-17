from database.database import Database


SCHEMA = (
    "CREATE TABLE IF NOT EXISTS scan_history (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, score REAL, signal TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS signal_history (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, signal TEXT, confidence REAL, score REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS watchlist (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT UNIQUE NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)",
)


def create_tables() -> None:
    db = Database()
    try:
        for statement in SCHEMA:
            db.execute(statement)
    finally:
        db.close()


if __name__ == "__main__":
    create_tables()
