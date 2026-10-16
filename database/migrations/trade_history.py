def migrate(db):

    db.execute("""
    CREATE TABLE IF NOT EXISTS trade_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        side TEXT,
        quantity INTEGER,
        entry_price REAL,
        exit_price REAL,
        stoploss REAL,
        target REAL,
        pnl REAL,
        status TEXT,
        broker_order_id TEXT,
        created_at DATETIME,
        closed_at DATETIME
    )
    """)

    columns = {
        str(row["name"])
        for row in db.fetchall(
            "PRAGMA table_info(trade_history)"
        )
    }
    if "closed_at" not in columns:
        db.execute(
            "ALTER TABLE trade_history "
            "ADD COLUMN closed_at DATETIME"
        )
