from __future__ import annotations

from database.database import Database
from database.migrations import watchlists
from database.repositories.watchlist_repository import WatchlistRepository
from services.watchlist_dashboard_service import WatchlistDashboardService


def build_service(tmp_path):
    db = Database(str(tmp_path / "watchlists.db"))
    watchlists.migrate(db)
    repo = WatchlistRepository(db=db)
    return db, WatchlistDashboardService(repository=repo)


def test_watchlist_upsert_persists_full_entry_contract(tmp_path):
    db, service = build_service(tmp_path)
    try:
        result = service.upsert(
            "Swing",
            symbol="tcs",
            notes="EMA setup",
            priority=4,
            target=3300.0,
            stoploss=3000.0,
            scanner="NIFTY500",
            score=91.5,
            last_signal="BUY",
            last_scan="2026-10-16T10:00:00+05:30",
        )

        entry = result["entry"]
        assert entry["symbol"] == "TCS"
        assert entry["priority"] == 4
        assert entry["target"] == 3300.0
        assert entry["stoploss"] == 3000.0
        assert entry["scanner"] == "NIFTY500"
        assert entry["score"] == 91.5
        assert entry["last_signal"] == "BUY"
    finally:
        db.close()


def test_watchlist_upsert_updates_existing_without_duplicate(tmp_path):
    db, service = build_service(tmp_path)
    try:
        service.upsert("Swing", symbol="TCS", priority=2)
        service.upsert(
            "Swing",
            symbol="TCS",
            priority=5,
            notes="Promoted",
        )

        detail = service.get("Swing")
        assert detail["count"] == 1
        assert detail["entries"][0]["priority"] == 5
        assert detail["entries"][0]["notes"] == "Promoted"
    finally:
        db.close()


def test_watchlist_summary_and_remove(tmp_path):
    db, service = build_service(tmp_path)
    try:
        service.upsert("Swing", symbol="TCS", priority=5, score=90)
        service.upsert("Swing", symbol="INFY", priority=2, score=80)
        service.upsert("Long Term", symbol="RELIANCE", priority=3)

        summary = service.summary()
        assert summary["watchlist_count"] == 2
        assert summary["symbol_count"] == 3
        assert summary["entry_count"] == 3

        swing = next(
            item
            for item in summary["watchlists"]
            if item["name"] == "Swing"
        )
        assert swing["count"] == 2
        assert swing["high_priority"] == 1
        assert swing["average_score"] == 85.0

        removed = service.remove("Swing", "INFY")
        assert removed["status"] == "removed"
        assert service.get("Swing")["count"] == 1
    finally:
        db.close()


def test_watchlist_validation_rejects_invalid_priority(tmp_path):
    db, service = build_service(tmp_path)
    try:
        try:
            service.upsert("Swing", symbol="TCS", priority=9)
        except ValueError as exc:
            assert "priority" in str(exc)
        else:
            raise AssertionError("invalid priority must fail")
    finally:
        db.close()
