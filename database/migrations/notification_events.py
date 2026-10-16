"""Persist canonical routed notification events."""
from __future__ import annotations


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            symbol TEXT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            source TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'discord',
            status TEXT NOT NULL,
            dedupe_key TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_notification_events_created
        ON notification_events(created_at DESC)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_notification_events_status
        ON notification_events(status, created_at DESC)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_notification_events_category
        ON notification_events(category, created_at DESC)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_notification_events_dedupe
        ON notification_events(dedupe_key, created_at DESC)
        """
    )
