"""Add continuation expiry and abuse-control state."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


DEFAULT_TTL_SECONDS = 3600
DEFAULT_MAX_CLAIM_ATTEMPTS = 3


def _columns(db):
    return {
        str(row["name"])
        for row in db.fetchall("PRAGMA table_info(scan_continuations)")
    }


def _parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def migrate(db):
    columns = _columns(db)

    additions = (
        (
            "expires_at",
            "ALTER TABLE scan_continuations ADD COLUMN expires_at TEXT",
        ),
        (
            "claim_attempts",
            "ALTER TABLE scan_continuations "
            "ADD COLUMN claim_attempts INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "max_claim_attempts",
            "ALTER TABLE scan_continuations "
            "ADD COLUMN max_claim_attempts INTEGER NOT NULL DEFAULT 3",
        ),
        (
            "recovery_count",
            "ALTER TABLE scan_continuations "
            "ADD COLUMN recovery_count INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "last_recovered_at",
            "ALTER TABLE scan_continuations ADD COLUMN last_recovered_at TEXT",
        ),
    )

    for name, statement in additions:
        if name not in columns:
            db.execute(statement)

    rows = db.fetchall(
        """
        SELECT id, created_at, expires_at
        FROM scan_continuations
        WHERE expires_at IS NULL OR TRIM(expires_at)=''
        """
    )
    for row in rows:
        created = _parse_timestamp(row["created_at"])
        expires = created + timedelta(seconds=DEFAULT_TTL_SECONDS)
        db.execute(
            "UPDATE scan_continuations SET expires_at=? WHERE id=?",
            (expires.isoformat(), int(row["id"])),
        )

    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scan_continuations_expires
        ON scan_continuations(expires_at, status)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scan_continuations_claimed
        ON scan_continuations(status, claimed_at)
        """
    )


__all__ = [
    "DEFAULT_MAX_CLAIM_ATTEMPTS",
    "DEFAULT_TTL_SECONDS",
    "migrate",
]
