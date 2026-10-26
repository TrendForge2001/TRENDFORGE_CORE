"""Mounted-disk restart evidence; never creates a replacement trading book."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from core.storage_config import resolve_storage, storage_health
from services.local_storage_service import verify_database

PROBE_KEY = "paper.cloud.storage.probe.v1"
PROOF_FILENAME = "paper-cloud-storage-proof.json"


def prepare_cloud_storage(*, boot_id: str) -> bool:
    """Return true only when a later server boot reads matching disk/DB evidence.

    Call before importing the application. The caller supplies a fresh random
    boot ID per process, never a user-controlled recovery flag.
    """
    if not re.fullmatch(r"[0-9a-f]{32}", boot_id):
        raise ValueError("Invalid process boot identity")
    report = storage_health()
    required = (
        "database_path_configured",
        "database_path_is_absolute",
        "persistent_mount_is_mountpoint",
        "database_within_persistent_mount",
    )
    if not all(report.get(key) is True for key in required):
        raise ValueError("A mounted persistent database is required")
    config = resolve_storage()
    mount = Path(str(report["persistent_mount"]))
    if not config.root.is_relative_to(mount):
        raise ValueError("The data directory must be on the persistent disk")
    database = config.database.resolve()
    proof = config.root / PROOF_FILENAME
    # Existing books are restored/initialized explicitly before this launcher.
    if not database.is_file() or verify_database(database)["status"] != "ok":
        raise ValueError("Preserve and restore the existing trading database")
    from core.database import REQUIRED_TABLES

    with closing(
        sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=5)
    ) as connection:
        connection.execute("BEGIN IMMEDIATE")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not set(REQUIRED_TABLES).issubset(tables):
            raise ValueError("The trading database schema must be initialized")
        row = connection.execute(
            "SELECT value FROM settings WHERE key=?", (PROBE_KEY,)
        ).fetchone()
        if row is not None:
            try:
                if proof.stat().st_size > 4096:
                    raise ValueError("Oversized evidence")
                saved = json.loads(row[0])
                companion = json.loads(proof.read_text(encoding="utf-8"))
                valid = (
                    isinstance(saved, dict)
                    and set(saved) == {"database", "boot", "nonce"}
                    and saved == companion
                    and saved["database"] == str(database)
                    and isinstance(saved["boot"], str)
                    and re.fullmatch(r"[0-9a-f]{32}", saved["boot"]) is not None
                    and isinstance(saved["nonce"], str)
                    and re.fullmatch(r"[0-9a-f]{64}", saved["nonce"]) is not None
                )
            except (OSError, ValueError, TypeError):
                valid = False
            if not valid:
                raise ValueError("Restart evidence does not match the trading book")
            return saved["boot"] != boot_id
        if proof.exists():
            raise ValueError("The trading book lost its restart evidence")
        import secrets

        payload = {
            "database": str(database),
            "boot": boot_id,
            "nonce": secrets.token_hex(32),
        }
        # An interrupted write leaves a mismatch and blocks the next boot.
        descriptor = os.open(proof, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        connection.execute(
            "INSERT INTO settings(key,value) VALUES (?,?)",
            (PROBE_KEY, json.dumps(payload)),
        )
        connection.commit()
    return False
