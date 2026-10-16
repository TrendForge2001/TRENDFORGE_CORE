from __future__ import annotations

from database.database import Database
from database.migrations import market_context_snapshots
from database.repositories.market_context_repository import (
    MarketContextRepository,
)


def test_market_context_repository_round_trips_payload(tmp_path):
    db = Database(str(tmp_path / "context.db"))
    try:
        market_context_snapshots.migrate(db)
        repo = MarketContextRepository(db=db)

        saved = repo.save(
            "breadth",
            {
                "status": "ready",
                "direction": "BULLISH",
                "breadth_score": 72.5,
            },
            universe="NIFTY 500",
            sample_size=100,
        )

        assert saved["kind"] == "breadth"
        assert saved["sample_size"] == 100
        assert saved["payload"]["direction"] == "BULLISH"

        loaded = repo.get("breadth")
        assert loaded is not None
        assert loaded["payload"]["breadth_score"] == 72.5
    finally:
        db.close()


def test_market_context_repository_upserts_latest_snapshot(tmp_path):
    db = Database(str(tmp_path / "context.db"))
    try:
        market_context_snapshots.migrate(db)
        repo = MarketContextRepository(db=db)

        repo.save(
            "regime",
            {"regime": "SIDEWAYS"},
            universe="NIFTY 500",
            sample_size=50,
        )
        repo.save(
            "regime",
            {"regime": "BULLISH"},
            universe="NIFTY 500",
            sample_size=100,
        )

        rows = repo.all()
        assert len(rows) == 1
        assert rows[0]["sample_size"] == 100
        assert rows[0]["payload"]["regime"] == "BULLISH"
    finally:
        db.close()
