from __future__ import annotations

from core.database import initialize_database
from database.repositories.trade_repository import TradeRepository


def test_trade_repository_daily_entry_risk_queries(tmp_path, monkeypatch):
    database = tmp_path / "trendforge.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    initialize_database()

    trades = TradeRepository()
    try:
        loss_id = trades.save(
            symbol="TCS",
            side="BUY",
            quantity=10,
            entry_price=100.0,
            stoploss=90.0,
            target=120.0,
            status="OPEN",
            created_at="2026-10-16T10:00:00+05:30",
        )
        win_id = trades.save(
            symbol="INFY",
            side="BUY",
            quantity=10,
            entry_price=100.0,
            stoploss=90.0,
            target=120.0,
            status="OPEN",
            created_at="2026-10-16T11:00:00+05:30",
        )
        trades.save(
            symbol="RELIANCE",
            side="BUY",
            quantity=1,
            entry_price=1000.0,
            stoploss=950.0,
            target=1100.0,
            status="OPEN",
            created_at="2026-10-15T11:00:00+05:30",
        )

        trades.close_trade(loss_id, 90.0)
        trades.close_trade(win_id, 120.0)

        assert trades.realized_pnl_for_entry_date(
            "2026-10-16"
        ) == 100.0
        assert trades.realized_loss_for_entry_date(
            "2026-10-16"
        ) == 100.0
        assert trades.has_trade_on_entry_date(
            "TCS",
            "2026-10-16",
        ) is True
        assert trades.has_trade_on_entry_date(
            "RELIANCE",
            "2026-10-16",
        ) is False
    finally:
        trades.close()
