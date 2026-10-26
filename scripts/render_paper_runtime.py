"""Start an existing mounted paper book with two-boot recovery verification."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3

from core.storage_config import resolve_storage
from scripts.local_engine_runtime import exclusive_lock
from services.cloud_paper_storage import prepare_cloud_storage


def configure_storage() -> bool:
    # Do not inherit an operator flag as restart evidence in this launcher.
    os.environ["TRENDFORGE_STORAGE_RECOVERY_VERIFIED"] = "false"
    os.environ["TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION"] = "false"
    os.environ["TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES"] = "false"
    os.environ["WEB_CONCURRENCY"] = "1"
    verified = prepare_cloud_storage(boot_id=secrets.token_hex(16))
    os.environ["TRENDFORGE_STORAGE_RECOVERY_VERIFIED"] = str(verified).lower()
    return verified


def main() -> int:
    try:
        port = int(os.getenv("PORT", "10000"))
        if not 1024 <= port <= 65535:
            raise ValueError("Invalid service port")
        verified = configure_storage()
        with exclusive_lock(resolve_storage().root / "paper-cloud-runtime.lock"):
            print(
                json.dumps(
                    {
                        "persistent_storage_verified": verified,
                        "phase": (
                            "restart_verified" if verified else "restart_required"
                        ),
                        "automation_auto_enabled": False,
                    }
                ),
                flush=True,
            )
            import uvicorn

            uvicorn.run("start:app", host="0.0.0.0", port=port, workers=1)
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        print(
            "Persistent paper startup blocked: check the mounted disk, existing "
            "database integrity/schema, matching restart evidence and "
            "whether another server holds the book lock. "
            "No replacement book was created.",
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
