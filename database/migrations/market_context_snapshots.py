"""Persist latest breadth/regime snapshots for dashboard reads."""
from __future__ import annotations


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS market_context_snapshots(
            kind TEXT PRIMARY KEY,
            universe TEXT NOT NULL,
            sample_size INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_market_context_created
        ON market_context_snapshots(created_at DESC)
        """
    )
