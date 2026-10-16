"""Persist R68.6 institutional and sector-strength snapshots."""
from __future__ import annotations


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS institutional_sector_snapshots(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            snapshot_key TEXT NOT NULL,
            universe TEXT,
            sample_size INTEGER,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(kind, snapshot_key)
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_institutional_sector_kind_created
        ON institutional_sector_snapshots(
            kind,
            created_at DESC
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_institutional_sector_key
        ON institutional_sector_snapshots(
            snapshot_key,
            created_at DESC
        )
        """
    )
