"""R70.3 durable, explicit sync journal. No automatic network activity."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4

EVENT_TYPES = frozenset({
    "heartbeat", "scanner_snapshot", "paper_position_snapshot",
    "portfolio_snapshot", "backtest_summary", "eod_report",
})
MAX_BODY_BYTES = 16384
FORBIDDEN_FIELDS = ("password", "secret", "token", "credential",
                    "api_key", "access_key", "authorization", "account_number")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def assert_safe_payload(value: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ValueError("Payload must be an object")
    def walk(obj: Any):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if any(word in str(k).lower() for word in FORBIDDEN_FIELDS):
                    raise ValueError("Payload contains a restricted field")
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(value)
    if len(canonical(value).encode("utf-8")) > MAX_BODY_BYTES:
        raise ValueError("Payload size exceeds 16 KiB")


class LocalOutbox:
    """Separate local SQLite journal. NEVER touch primary trading DB."""
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @classmethod
    def from_environment(cls) -> "LocalOutbox":
        from scripts.local_engine_runtime import preflight, paths
        if preflight().get("status") != "ready":
            raise RuntimeError("PC database preflight failed")
        root, _ = paths()
        return cls(root / "sync" / "outbox.db")

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute(
            """CREATE TABLE IF NOT EXISTS outgoing_events(
                event_id TEXT PRIMARY KEY,
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                acknowledged_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0
            )"""
        )
        db.commit()
        return db

    def enqueue(self, event_type: str, payload: dict[str, Any]) -> str:
        if event_type not in EVENT_TYPES:
            raise ValueError("Unknown sync event type")
        assert_safe_payload(payload)
        event_id = str(uuid4())
        event = {"version": 1, "event_id": event_id,
                 "event_type": event_type, "created_at": utc_now(),
                 "payload": payload}
        encoded = canonical(event)
        if len(encoded.encode("utf-8")) > MAX_BODY_BYTES:
            raise ValueError("Event size exceeds 16 KiB")
        with closing(self._connect()) as db:
            with db:
                db.execute(
                    "INSERT INTO outgoing_events(event_id,event_json,created_at) VALUES (?,?,?)",
                    (event_id, encoded, event["created_at"]),
                )
        return event_id

    def pending(self, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 20:
            raise ValueError("Limit must be 1..20")
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT event_json FROM outgoing_events WHERE acknowledged_at IS NULL "
                "ORDER BY created_at, rowid LIMIT ?", (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def acknowledge(self, event_id: str) -> None:
        with closing(self._connect()) as db:
            with db:
                db.execute(
                    "UPDATE outgoing_events SET acknowledged_at=? "
                    "WHERE event_id=? AND acknowledged_at IS NULL",
                    (utc_now(), event_id),
                )

    def note_attempt(self, event_id: str) -> None:
        with closing(self._connect()) as db:
            with db:
                db.execute(
                    "UPDATE outgoing_events SET attempts=attempts+1 "
                    "WHERE event_id=? AND acknowledged_at IS NULL", (event_id,),
                )

    def status(self) -> dict[str, int]:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT COUNT(*), SUM(CASE WHEN acknowledged_at IS NULL THEN 1 ELSE 0 END) "
                "FROM outgoing_events"
            ).fetchone()
        return {"total": row[0], "pending": row[1] or 0}


def cloud_receiver_readiness(environ=None, *, mount_check=os.path.ismount) -> dict[str, str]:
    """Refuse writes on Render Free's ephemeral filesystem."""
    env = os.environ if environ is None else environ
    if env.get("TRENDFORGE_SYNC_RECEIVER_ENABLED", "").lower() != "true":
        return {"status": "disabled"}
    key = env.get("TRENDFORGE_SYNC_SHARED_KEY", "")
    if len(key) < 32:
        return {"status": "blocked", "reason": "shared_key_not_configured"}
    root = env.get("TRENDFORGE_SYNC_STORAGE_ROOT", "").strip()
    if not root:
        return {"status": "blocked", "reason": "durable_volume_not_configured"}
    directory = Path(root).resolve()
    if not directory.is_dir() or not mount_check(str(directory)):
        return {"status": "blocked", "reason": "durable_volume_not_verified"}
    return {"status": "ready"}


class DurableInbox:
    """SQLite inbox must only be constructed after verified persistent mount gate."""
    def __init__(self, db_file: str | Path):
        self.db_file = Path(db_file)

    def store(self, event: dict[str, Any]) -> dict[str, Any]:
        if event.get("version") != 1:
            raise ValueError("Unsupported sync protocol version")
        if event.get("event_type") not in EVENT_TYPES:
            raise ValueError("Unknown sync event type")
        if not isinstance(event.get("event_id"), str) or len(event["event_id"]) != 36:
            raise ValueError("Invalid event identifier")
        if not isinstance(event.get("created_at"), str):
            raise ValueError("Missing timestamp")
        assert_safe_payload(event.get("payload"))
        encoded = canonical(event)
        if len(encoded.encode("utf-8")) > MAX_BODY_BYTES:
            raise ValueError("Event size exceeds 16 KiB")
        # Parent must already exist: NEVER silently create a cloud storage location.
        with closing(sqlite3.connect(self.db_file, timeout=15)) as db:
            db.execute("PRAGMA busy_timeout=15000")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                db.execute(
                    """CREATE TABLE IF NOT EXISTS received_events(
                        event_id TEXT PRIMARY KEY,
                        event_json TEXT NOT NULL,
                        received_at TEXT NOT NULL
                    )"""
                )
                row = db.execute(
                    "SELECT event_json FROM received_events WHERE event_id=?",
                    (event["event_id"],),
                ).fetchone()
                if row is not None and row[0] != encoded:
                    raise ValueError("Conflicting event ID")
                if row is None:
                    db.execute(
                        "INSERT INTO received_events VALUES (?,?,?)",
                        (event["event_id"], encoded, utc_now()),
                    )
        return {"event_id": event["event_id"], "durable": True,
                "duplicate": row is not None}


def sync_sender_config(environ=None) -> dict[str, str]:
    env = os.environ if environ is None else environ
    if env.get("TRENDFORGE_SYNC_SENDER_ENABLED", "").lower() != "true":
        raise RuntimeError("Sync sender disabled")
    endpoint = env.get("TRENDFORGE_SYNC_URL", "")
    parts = urlsplit(endpoint)
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment
            or parts.path != "/sync/events"):
        raise ValueError("Sync target must be an HTTPS /sync/events endpoint")
    key = env.get("TRENDFORGE_SYNC_SHARED_KEY", "")
    if len(key) < 32:
        raise RuntimeError("Sync shared key is not configured")
    return {"endpoint": endpoint, "key": key}


def send_once(outbox: LocalOutbox, *,
              transport: Callable[[str, str, dict[str, Any]], tuple[int, dict]] | None = None,
              environ=None) -> dict:
    """Explicit opt-in and confirmed durable ACK only. No periodic/background send."""
    config = sync_sender_config(environ)
    if transport is None:
        import httpx
        def transport(url, key, event):
            with httpx.Client(timeout=10.0, follow_redirects=False) as client:
                response = client.post(
                    url, json=event, headers={"X-TrendForge-Sync-Key": key})
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                return response.status_code, body
    attempted = 0
    acknowledged = 0
    for event in outbox.pending(20):
        attempted += 1
        outbox.note_attempt(event["event_id"])
        try:
            status, response = transport(config["endpoint"], config["key"], event)
        except Exception:
            # No automatic ACK on timeout or network failure.
            break
        if (status == 200 and isinstance(response, dict)
                and response.get("event_id") == event["event_id"]
                and response.get("durable") is True):
            outbox.acknowledge(event["event_id"])
            acknowledged += 1
        else:
            break
    return {"attempted": attempted, "acknowledged": acknowledged,
            "pending": outbox.status()["pending"]}
