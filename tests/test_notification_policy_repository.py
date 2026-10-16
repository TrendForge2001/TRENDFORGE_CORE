from __future__ import annotations

from database.database import Database
from database.migrations import settings
from database.repositories.notification_policy_repository import (
    NotificationPolicyRepository,
)


def test_notification_policy_repository_round_trip(tmp_path):
    db = Database(str(tmp_path / "policy.db"))
    try:
        settings.migrate(db)
        repo = NotificationPolicyRepository(db=db)

        assert repo.get() is None
        saved = repo.set(
            {
                "version": "R68.9",
                "delivery_enabled": False,
            }
        )

        loaded = repo.get()
        assert loaded is not None
        assert loaded["policy"]["delivery_enabled"] is False
        assert loaded["updated_at"] == saved["updated_at"]

        assert repo.reset() is True
        assert repo.get() is None
        assert repo.reset() is False
    finally:
        db.close()
