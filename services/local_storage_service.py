"""Read-only database verification and safe SQLite online backups."""
from __future__ import annotations

import hashlib
from contextlib import closing
import os
import sqlite3
import tempfile
from pathlib import Path


def verify_database(path: str | Path) -> dict:
    source = Path(path)
    if not source.is_file():
        return {"status": "missing", "path": str(source)}
    try:
        with closing(sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        return {"status": "ok" if integrity == "ok" else "corrupt",
                "path": str(source), "integrity": integrity,
                "table_count": len(tables)}
    except (OSError, sqlite3.Error) as exc:
        return {"status": "error", "path": str(source), "error": str(exc)}


def backup_database(source: str | Path, destination: str | Path) -> dict:
    """Backup using SQLite API, verify before atomic publish, never overwrite."""
    src, dst = Path(source), Path(destination)
    if not src.is_file():
        raise FileNotFoundError(src)
    if src.resolve() == dst.resolve():
        raise ValueError("Source and destination must differ")
    if dst.exists():
        raise FileExistsError(dst)
    if verify_database(src)["status"] != "ok":
        raise ValueError("Source integrity check failed")
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".trendforge-backup-", suffix=".db", dir=dst.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with closing(sqlite3.connect(f"file:{src.resolve().as_posix()}?mode=ro", uri=True)) as input_db:
            with closing(sqlite3.connect(str(temp))) as output_db:
                input_db.backup(output_db)
        if verify_database(temp)["status"] != "ok":
            raise ValueError("Backup integrity check failed")
        # Hard link publishes without overwriting a pre-existing destination.
        os.link(temp, dst)
        digest = hashlib.sha256(dst.read_bytes()).hexdigest()
        return {"status": "verified", "destination": str(dst), "sha256": digest,
                "bytes": dst.stat().st_size}
    finally:
        temp.unlink(missing_ok=True)


def migrate_database(source: str | Path, destination: str | Path) -> dict:
    """Copy-only migration: the original database is never deleted or altered."""
    result = backup_database(source, destination)
    result["source_preserved"] = True
    return result
