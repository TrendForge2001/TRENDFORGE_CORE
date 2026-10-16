from __future__ import annotations

from database.database import Database
from database.migrations import trade_history
from database.repositories.trade_repository import TradeRepository


def test_trade_history_migration_adds_closed_at_to_legacy_table(
    tmp_path,
):
    db = Database(str(tmp_path / "legacy.db"))
    try:
        db.execute(
            """
            CREATE TABLE trade_history(
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
                created_at DATETIME
            )
            """
        )

        trade_history.migrate(db)

        columns = {
            row["name"]
            for row in db.fetchall(
                "PRAGMA table_info(trade_history)"
            )
        }
        assert "closed_at" in columns
    finally:
        db.close()


def test_close_trade_persists_realized_timestamp(tmp_path):
    db = Database(str(tmp_path / "trades.db"))
    try:
        trade_history.migrate(db)
        repo = TradeRepository(db=db)
        trade_id = repo.save(
            symbol="TCS",
            side="BUY",
            quantity=2,
            entry_price=3000.0,
            status="OPEN",
        )

        repo.close_trade(trade_id, 3100.0)

        row = repo.get(trade_id)
        assert row["status"] == "CLOSED"
        assert row["pnl"] == 200.0
        assert row["closed_at"]
        assert "+05:30" in str(row["closed_at"])
    finally:
        db.close()
