"""Read-only TrendForge retention inventory. Run on the host with the mounted book."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter
from pathlib import Path


def preview(db_path):
    path = Path(db_path).resolve(strict=True)
    archive_root = (path.parent.parent if path.parent.name == "database" else path.parent) / "reports/research"
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("BEGIN")
        page = db.execute("PRAGMA page_size").fetchone()[0]
        free = db.execute("PRAGMA freelist_count").fetchone()[0] * page
        rows = db.execute("""SELECT batch_id,kind,strategy_id,status,created_at,
            json_extract(request_json,'$.parent_batch_id'),
            json_extract(request_json,'$.scan_retry_of'),
            length(CAST(report_json AS BLOB))
            FROM research_batches ORDER BY created_at DESC,batch_id DESC""")
        records = list(rows)
    finally:
        db.close()

    parents = {r[0]: r[5] or r[6] for r in records}
    groups = {}
    for row in records:
        key = row[0]
        seen = set()
        while parents.get(key) and key not in seen:
            seen.add(key)
            key = parents[key]
        groups.setdefault(key, []).append(row)

    counts = Counter()
    candidates = []
    for key, kind, strategy, status, created, parent, retry, size in records:
        if parent or retry or status != "completed" or size is None:
            continue
        bucket = (kind, strategy if kind == "backtest" else "")
        counts[bucket] += 1
        if counts[bucket] <= (10 if kind == "scan" else 3):
            continue
        members = groups[key]
        if any(r[3] in {"queued", "running"} for r in members):
            continue
        archive_bytes = 0
        for member in members:
            folder = archive_root / hashlib.sha256(member[0].encode()).hexdigest()
            if folder.is_dir() and not folder.is_symlink():
                archive_bytes += sum(f.stat().st_size for f in folder.iterdir()
                                     if not f.is_symlink() and f.is_file())
        candidates.append(dict(run=key, kind=kind, strategy=strategy, created=created,
                               archive_file_bytes=archive_bytes,
                               database_payload_bytes=sum(r[7] or 0 for r in members)))
    return dict(filesystem_free_bytes=shutil.disk_usage(path).free,
                sqlite_reusable_bytes=free, age_candidates=candidates,
                review="Age candidates only. Verify pins, readiness evidence, dependent jobs and preserved summaries before deletion. Database payload bytes are not filesystem savings.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", nargs="?", default=os.getenv("DATABASE_PATH") or
                        str(Path(os.getenv("TRENDFORGE_DATA_DIR", "/var/data")) / "database/trendforge.db"))
    print(json.dumps(preview(parser.parse_args().database), indent=2))
