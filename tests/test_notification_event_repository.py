from __future__ import annotations

from database.database import Database
from database.migrations import notification_events
from database.repositories.notification_event_repository import (
    NotificationEventRepository,
)


def test_notification_repository_persists_and_updates(tmp_path):
    db = Database(str(tmp_path / "notifications.db"))
    try:
        notification_events.migrate(db)
        repo = NotificationEventRepository(db=db)

        created = repo.create(
            {
                "event_id": "evt-1",
                "event_type": "scanner_pick",
                "category": "scanner",
                "severity": "INFO",
                "symbol": "TCS",
                "title": "Scanner Alert",
                "message": "TCS passed",
                "source": "scanner",
                "channel": "discord",
                "status": "recorded",
                "dedupe_key": "dedupe-1",
                "payload": {"score": 92},
            }
        )
        assert created["payload"]["score"] == 92

        updated = repo.update_delivery(
            "evt-1",
            status="sent",
            sent_at="2026-10-16T10:00:00+00:00",
        )
        assert updated is not None
        assert updated["status"] == "sent"
        assert updated["sent_at"] == "2026-10-16T10:00:00+00:00"
        assert repo.count(status="sent") == 1
    finally:
        db.close()


def test_notification_repository_filters_and_dedupe(tmp_path):
    db = Database(str(tmp_path / "notifications.db"))
    try:
        notification_events.migrate(db)
        repo = NotificationEventRepository(db=db)
        for index, category in enumerate(("scanner", "risk"), start=1):
            repo.create(
                {
                    "event_id": f"evt-{index}",
                    "event_type": "event",
                    "category": category,
                    "severity": "INFO",
                    "symbol": "TCS",
                    "title": category,
                    "message": category,
                    "source": "test",
                    "channel": "discord",
                    "status": "sent",
                    "dedupe_key": f"key-{index}",
                    "created_at": "2026-10-16T10:00:00+00:00",
                }
            )

        assert len(repo.latest(category="scanner")) == 1
        assert len(repo.latest(status="sent", symbol="TCS")) == 2
        assert repo.category_counts() == {
            "risk": 1,
            "scanner": 1,
        }
        duplicate = repo.recent_dedupe(
            "key-1",
            since="2026-10-16T09:00:00+00:00",
        )
        assert duplicate is not None
        assert duplicate["event_id"] == "evt-1"
    finally:
        db.close()


def test_notification_repository_daily_window_and_find_dedupe(tmp_path):
    db = Database(str(tmp_path / "notifications.db"))
    try:
        notification_events.migrate(db)
        repo = NotificationEventRepository(db=db)
        for event_id, created_at, status in (
            ("evt-a", "2026-10-15T18:29:59+00:00", "sent"),
            ("evt-b", "2026-10-15T18:30:00+00:00", "sent"),
            ("evt-c", "2026-10-16T12:00:00+00:00", "filtered"),
            ("evt-d", "2026-10-16T18:29:59+00:00", "recorded"),
            ("evt-e", "2026-10-16T18:30:00+00:00", "sent"),
        ):
            repo.create(
                {
                    "event_id": event_id,
                    "event_type": "event",
                    "category": "system",
                    "severity": "INFO",
                    "title": event_id,
                    "message": event_id,
                    "source": "test",
                    "channel": "discord",
                    "status": status,
                    "dedupe_key": (
                        "daily-summary:2026-10-16"
                        if event_id == "evt-d"
                        else event_id
                    ),
                    "created_at": created_at,
                }
            )

        rows = repo.between(
            start="2026-10-15T18:30:00+00:00",
            end="2026-10-16T18:30:00+00:00",
        )

        assert [row["event_id"] for row in rows] == [
            "evt-b",
            "evt-c",
            "evt-d",
        ]
        found = repo.find_dedupe(
            "daily-summary:2026-10-16",
        )
        assert found is not None
        assert found["event_id"] == "evt-d"
    finally:
        db.close()
