"""Canonical persisted evidence for news and corporate actions."""
from __future__ import annotations


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE,
            domain TEXT NOT NULL,
            symbol TEXT NOT NULL,
            event_type TEXT,
            headline TEXT,
            summary TEXT,
            source TEXT,
            publisher TEXT,
            url TEXT,
            event_at TEXT,
            sentiment_label TEXT,
            sentiment_score REAL,
            impact_score REAL,
            details_json TEXT NOT NULL DEFAULT '{}',
            fetched_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_intelligence_symbol_event
        ON intelligence_events(symbol, event_at DESC, id DESC)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_intelligence_domain_event
        ON intelligence_events(domain, event_at DESC, id DESC)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_intelligence_type_event
        ON intelligence_events(event_type, event_at DESC, id DESC)
        """
    )
