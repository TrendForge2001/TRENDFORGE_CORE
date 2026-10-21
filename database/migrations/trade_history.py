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
        closed_at DATETIME,
        trade_mode TEXT DEFAULT 'intraday',
        strategy_id TEXT,
        strategy_name TEXT,
        strategy_source TEXT,
        source_scan_run_id TEXT,
        validation_run_id TEXT,
        strategy_score REAL,
        consensus_score REAL,
        entry_signal TEXT,
        entry_bar_at DATETIME,
        exit_reason TEXT,
        exit_signal TEXT,
        exit_signal_at DATETIME,
        exit_strategy_score REAL
    )
    """)

    columns = {
        str(row["name"])
        for row in db.fetchall(
            "PRAGMA table_info(trade_history)"
        )
    }
    required = {
        "closed_at": "DATETIME",
        "trade_mode": "TEXT DEFAULT 'intraday'",
        "strategy_id": "TEXT",
        "strategy_name": "TEXT",
        "strategy_source": "TEXT",
        "source_scan_run_id": "TEXT",
        "validation_run_id": "TEXT",
        "strategy_score": "REAL",
        "consensus_score": "REAL",
        "entry_signal": "TEXT",
        "entry_bar_at": "DATETIME",
        "exit_reason": "TEXT",
        "exit_signal": "TEXT",
        "exit_signal_at": "DATETIME",
        "exit_strategy_score": "REAL",
    }
    for name, sql_type in required.items():
        if name not in columns:
            db.execute(
                f"ALTER TABLE trade_history ADD COLUMN {name} {sql_type}"
            )
