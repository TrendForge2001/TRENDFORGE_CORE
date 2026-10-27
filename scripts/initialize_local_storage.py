"""R70.1 CLI; defaults to inspection, requires explicit flags for writes."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from core.storage_config import initialize_directories, resolve_storage
from services.local_storage_service import backup_database, migrate_database, verify_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TrendForge local storage foundation")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--init", action="store_true", help="Create empty directories only")
    actions.add_argument("--verify", metavar="DB", help="Read-only SQLite integrity check")
    actions.add_argument("--backup", metavar="DB", help="Backup DB to configured backups directory")
    actions.add_argument("--migrate", nargs=2, metavar=("SOURCE", "DESTINATION"),
                         help="Safe copy-only migration; never overwrites destination")
    args = parser.parse_args(argv)
    config = resolve_storage()
    if args.init:
        result = {"status": "directories_ready",
                  "paths": initialize_directories(config, create=True)}
    elif args.verify:
        result = verify_database(args.verify)
    elif args.backup:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = config.directory("backups") / f"trendforge-{stamp}.db"
        result = backup_database(args.backup, destination)
    elif args.migrate:
        result = migrate_database(*args.migrate)
    else:
        result = {"status": "inspection_only", "data_root": str(config.root),
                  "database": str(config.database),
                  "paths": initialize_directories(config)}
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") not in {"error", "corrupt", "missing"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
