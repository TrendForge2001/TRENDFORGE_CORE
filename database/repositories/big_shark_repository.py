"""Owner-only snapshots live in the configured private operational database."""

from __future__ import annotations

import json
from uuid import uuid4

from database.database import Database
from services.big_shark_portfolio import serialise


class BigSharkSnapshotConflict(ValueError):
    pass


class BigSharkRepository:
    def __init__(self, db_path=None):
        self.db = Database(db_path)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS big_shark_portfolios (
                snapshot_id TEXT PRIMARY KEY,
                source_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS big_shark_source_state (
                state_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL
            )
        """)

    def save(self, snapshot, *, expected_snapshot_id=None, expected_absent=False):
        with self.db._lock, self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            row = self.db.conn.execute(
                "SELECT payload_json FROM big_shark_portfolios "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            latest = json.loads(row["payload_json"]) if row else None
            if expected_absent and latest is not None:
                raise BigSharkSnapshotConflict(
                    "Portfolio changed; reload before saving."
                )
            if expected_snapshot_id is not None and (
                not latest or latest["snapshot_id"] != expected_snapshot_id
            ):
                raise BigSharkSnapshotConflict(
                    "Portfolio changed; reload before saving."
                )
            return self._save(snapshot, latest)

    def _save(self, snapshot, latest):
        # Content identity includes explicit mappings and quarter, not import time.
        if latest and all(
            latest.get(k) == snapshot.get(k)
            for k in ("source_sha256", "signals", "reporting_period", "metric", "rule")
        ):
            return latest
        snapshot = {**snapshot, "snapshot_id": uuid4().hex}
        self.db.conn.execute(
            "INSERT INTO big_shark_portfolios VALUES (?, ?, ?, ?)",
            (
                snapshot["snapshot_id"],
                snapshot["source_sha256"],
                snapshot["imported_at"],
                serialise(snapshot),
            ),
        )
        return snapshot

    def latest(self):
        row = self.db.fetchone(
            "SELECT payload_json FROM big_shark_portfolios ORDER BY rowid DESC LIMIT 1"
        )
        return json.loads(row["payload_json"]) if row else None

    def has_source(self, digest):
        return (
            self.db.fetchone(
                "SELECT 1 FROM big_shark_portfolios WHERE source_sha256 = ? LIMIT 1",
                (digest,),
            )
            is not None
        )

    def source_state(self, key="latest"):
        row = self.db.fetchone(
            "SELECT payload_json FROM big_shark_source_state WHERE state_key=?", (key,)
        )
        return json.loads(row["payload_json"]) if row else None

    def save_source_state(self, payload, key="latest"):
        self.db.execute(
            "INSERT INTO big_shark_source_state(state_key,payload_json) VALUES (?,?) "
            "ON CONFLICT(state_key) DO UPDATE SET payload_json=excluded.payload_json",
            (key, serialise(payload)),
        )

    def close(self):
        self.db.close()
