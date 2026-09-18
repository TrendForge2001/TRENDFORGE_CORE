"""Migration for broker-sourced live portfolio books."""

def migrate(db):
    db.execute("""
    CREATE TABLE IF NOT EXISTS live_portfolio(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        exchange TEXT NOT NULL,
        sector TEXT,
        book TEXT NOT NULL,
        product TEXT,
        quantity INTEGER NOT NULL,
        average_price REAL NOT NULL,
        ltp REAL NOT NULL,
        investment REAL NOT NULL,
        current_value REAL NOT NULL,
        pnl REAL NOT NULL,
        updated_at DATETIME NOT NULL,
        UNIQUE(symbol, exchange, book, product)
    )
    """)
