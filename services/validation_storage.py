"""Losslessly rewrite private validation journals; never remove trading books."""

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import zlib
from pathlib import Path

from core.storage_config import resolve_storage
from services.validation_journal import KINDS, row_bytes

MINIMUM_FREE = 192 * 1024**2
TARGET_FREE = 256 * 1024**2


def storage_report(root):
    """Counts only, without paths, symbols, account values or file contents."""
    root = Path(root)
    mount = Path(os.getenv("TRENDFORGE_PERSISTENT_MOUNT") or root).resolve()
    if root.resolve().is_relative_to(mount) and mount.is_dir():
        root = mount
    usage = shutil.disk_usage(root)
    buckets = dict(journals=0, replay=0, other=0)
    seen = set()
    for path in root.rglob("*"):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) in seen:
            continue
        seen.add((info.st_dev, info.st_ino))
        group = (
            "journals"
            if (path.parent == root or path.parent.name == "validation")
            and path.suffix == ".sqlite"
            else "replay"
            if any(p.name.endswith("-replay") for p in path.parents)
            else "other"
        )
        buckets[group] += info.st_size
    return dict(total_bytes=usage.total, free_bytes=usage.free, logical_bytes=buckets)


def _digest(connection):
    digest = hashlib.sha256()
    meta = connection.execute("SELECT id,payload FROM meta ORDER BY id").fetchall()
    digest.update(json.dumps(meta, separators=(",", ":")).encode())
    units = 0
    counts = [0, 0, 0]
    for row in connection.execute("SELECT * FROM units ORDER BY rowid"):
        # Length framing avoids ambiguous concatenation across row boundaries.
        for value in (*row[:2], *(row_bytes(v) for v in row[2:5]), *row[5:]):
            content = value if isinstance(value, bytes) else str(value).encode()
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        counts = [a + b for a, b in zip(counts, row[5:], strict=True)]
        units += 1
    return dict(sha256=digest.hexdigest(), units=units, row_counts=counts)


def compact_journal(path):
    """Atomic replacement only after full semantic digest and SQLite validation.

    Uses a new compact database, so reclaimed pages return to the filesystem
    without VACUUM's requirement for a second uncompressed database copy.
    Interrupted staging leaves the original journal untouched.
    """
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("A regular validation journal is required")
    staging = path.with_name(path.name + ".compact")
    if staging.exists():
        raise ValueError("An interrupted journal compaction needs inspection")
    source = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)
    target = None
    before = path.stat().st_size
    try:
        source.execute("BEGIN IMMEDIATE")
        tables = source.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        extra = source.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') "
            "OR (type='index' AND sql IS NOT NULL)"
        ).fetchone()
        columns = [r[1] for r in source.execute("PRAGMA table_info(units)")]
        if (
            {row[0] for row in tables} != {"meta", "units"}
            or extra
            or columns != ["mode", "symbol", *KINDS, *(f"{k}_count" for k in KINDS)]
        ):
            raise ValueError("Unsupported journal schema; original retained")
        target = sqlite3.connect(staging)
        os.chmod(staging, 0o600)
        target.execute("PRAGMA journal_mode=OFF")  # disposable staging only
        for _, sql in tables:
            target.execute(sql)
        target.executemany(
            "INSERT INTO meta VALUES(?,?)", source.execute("SELECT * FROM meta")
        )
        for row in source.execute("SELECT * FROM units ORDER BY rowid"):
            if shutil.disk_usage(path.parent).free < 32 * 1024**2:
                raise OSError("Not enough staging headroom; original retained")
            payloads = [zlib.compress(row_bytes(v)) for v in row[2:5]]
            target.execute(
                "INSERT INTO units VALUES(?,?,?,?,?,?,?,?)",
                (*row[:2], *payloads, *row[5:]),
            )
        target.commit()
        evidence = _digest(source)
        if (
            _digest(target) != evidence
            or target.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
        ):
            raise ValueError("Journal verification failed; original retained")
        target.close()
        target = None
        after = staging.stat().st_size
        if after >= before:
            return dict(
                changed=False, bytes_before=before, bytes_after=before, **evidence
            )
        with staging.open("r+b") as handle:
            os.fsync(handle.fileno())
        source.close()
        source = None
        os.replace(staging, path)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return dict(changed=True, bytes_before=before, bytes_after=after, **evidence)
    finally:
        if source is not None:
            source.close()
        if target is not None:
            target.close()
        staging.unlink(missing_ok=True)


def recover_storage(run_id):
    """Preserve all checkpoint content; never touch replay inputs or reports."""
    root = resolve_storage().database.resolve().parent / "validation"
    current = root / (hashlib.sha256(run_id.encode()).hexdigest() + ".sqlite")
    if not current.is_file():
        raise ValueError("Saved validation journal is unavailable")
    before = storage_report(root)
    reports = [compact_journal(current)]
    for path in sorted(
        root.glob("*.sqlite"), key=lambda p: p.stat().st_size, reverse=True
    ):
        if shutil.disk_usage(root).free >= TARGET_FREE:
            break
        if path != current:
            reports.append(compact_journal(path))
    after = storage_report(root)
    return dict(
        before=before,
        after=after,
        journals_compacted=sum(r["changed"] for r in reports),
        bytes_reclaimed=sum(r["bytes_before"] - r["bytes_after"] for r in reports),
        current_checkpoint=reports[0],
        sufficient_headroom=after["free_bytes"] >= MINIMUM_FREE,
        original_cutoff_and_payloads_preserved=True,
    )
