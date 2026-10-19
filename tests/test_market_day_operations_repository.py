from __future__ import annotations

from database.database import Database
from database.migrations import settings
from database.repositories.market_day_operations_repository import (
    MarketDayOperationsRepository,
)


def build_repo(tmp_path):
    db = Database(str(tmp_path / "operations.db"))
    settings.migrate(db)
    return db, MarketDayOperationsRepository(db=db)


def test_policy_round_trip_and_reset(tmp_path):
    db, repo = build_repo(tmp_path)
    try:
        assert repo.policy() is None

        saved = repo.set_policy(
            {
                "version": "R69.0",
                "automation_enabled": True,
            }
        )
        loaded = repo.policy()

        assert loaded is not None
        assert loaded["policy"]["automation_enabled"] is True
        assert loaded["updated_at"] == saved["updated_at"]

        assert repo.reset_policy() is True
        assert repo.policy() is None
        assert repo.reset_policy() is False
    finally:
        db.close()


def test_run_history_and_success_dedupe(tmp_path):
    db, repo = build_repo(tmp_path)
    try:
        repo.record_run(
            {
                "run_id": "one",
                "operation": "morning",
                "date_ist": "2026-10-16",
                "status": "failed",
            }
        )
        repo.record_run(
            {
                "run_id": "two",
                "operation": "morning",
                "date_ist": "2026-10-16",
                "status": "completed",
            }
        )
        repo.record_run(
            {
                "run_id": "three",
                "operation": "eod",
                "date_ist": "2026-10-16",
                "status": "completed",
            }
        )

        latest = repo.runs(limit=2)
        assert [row["run_id"] for row in latest] == [
            "three",
            "two",
        ]

        success = repo.successful_run(
            "morning",
            "2026-10-16",
        )
        assert success is not None
        assert success["run_id"] == "two"
    finally:
        db.close()


def test_audit_ledger_is_bounded_and_filterable(tmp_path):
    db, repo = build_repo(tmp_path)
    try:
        for index in range(305):
            repo.record_audit_event(
                {
                    "audit_id": str(index),
                    "event_key": f"event-{index}",
                    "operation": (
                        "morning"
                        if index % 2 == 0
                        else "eod"
                    ),
                }
            )

        rows = repo.audit_events(limit=300)
        assert len(rows) == 300
        assert rows[0]["audit_id"] == "304"
        assert rows[-1]["audit_id"] == "5"

        morning = repo.audit_events(
            limit=300,
            operation="morning",
        )
        assert morning
        assert all(
            row["operation"] == "morning"
            for row in morning
        )

        found = repo.audit_event("event-304")
        assert found is not None
        assert found["audit_id"] == "304"
        assert repo.audit_event("missing") is None
    finally:
        db.close()
