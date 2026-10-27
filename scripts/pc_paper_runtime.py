"""Run the unified paper webapp on a Windows PC with restart-verified SQLite."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.local_engine_runtime import exclusive_lock

PROBE_KEY = "paper.pc.storage.probe.v1"


def fixed_drive_mount(root: Path) -> str:
    """A PC disk is local infrastructure; never pretend a cloud path is one."""
    if os.name != "nt":
        raise ValueError("The PC launcher requires Windows")
    import ctypes

    mount = root.anchor
    if not mount or mount.startswith("\\\\"):
        raise ValueError("Choose a local fixed PC drive")
    if ctypes.windll.kernel32.GetDriveTypeW(mount) != 3:
        raise ValueError("Paper data must be on a local fixed PC drive")
    return mount


def prepare_storage(root: Path, *, session_id: str) -> tuple[Path, bool]:
    """Record an initial probe; only a later process can verify its read-back.

    A missing or mismatched existing database/probe stops startup. No old book,
    trading rows, settings or verification evidence is overwritten.
    """
    from core.database import initialize_database

    database = root / "database" / "trendforge.db"
    proof = root / "paper-storage-proof.json"
    if proof.exists() and not database.is_file():
        raise ValueError(
            "Previously verified database is missing; restore the PC ledger"
        )
    os.environ["DATABASE_PATH"] = str(database)
    initialize_database()
    with closing(sqlite3.connect(database)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("PC database integrity check failed")
        row = connection.execute(
            "SELECT value FROM settings WHERE key=?", (PROBE_KEY,)
        ).fetchone()
        if row is not None:
            try:
                saved = json.loads(row[0])
                companion = json.loads(proof.read_text(encoding="utf-8"))
                valid = (
                    saved == companion
                    and saved["database"] == str(database)
                    and isinstance(saved["session"], str)
                    and isinstance(saved["nonce"], str)
                    and len(saved["nonce"]) == 64
                )
            except (KeyError, OSError, TypeError, ValueError):
                valid = False
            if not valid:
                raise ValueError(
                    "PC restart proof does not match; "
                    "preserve and inspect the existing ledger"
                )
            return database, saved["session"] != session_id
        if proof.exists():
            raise ValueError(
                "PC database lost its restart probe; restore the existing ledger"
            )
        payload = {
            "database": str(database),
            "session": session_id,
            "nonce": secrets.token_hex(32),
        }
        # Exclusive creation prevents replacing another installation's evidence.
        with proof.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle)
        connection.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?)",
            (PROBE_KEY, json.dumps(payload)),
        )
        connection.commit()
    return database, False


def admin_key(root: Path, *, filename: str = "admin-key.txt") -> str:
    if filename not in {"admin-key.txt", "webapp-key.txt"}:
        raise ValueError("Unknown local credential file")
    target = root / "private" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(secrets.token_hex(32))
    value = target.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise ValueError(
            "The local administrative key is invalid; inspect the private settings"
        )
    return value


def configure(root: Path, *, port: int, session_id: str) -> bool:
    if not root.is_absolute() or not 1024 <= port <= 65535:
        raise ValueError(
            "Use an absolute data folder and a port between 1024 and 65535"
        )
    mount = fixed_drive_mount(root)
    from core.pc_kite_credentials import load_pc_kite_credentials

    os.environ.update(load_pc_kite_credentials(root))
    # Override inherited cloud and execution flags before importing the app.
    os.environ.update(
        {
            "TRENDFORGE_DATA_DIR": str(root),
            "TRENDFORGE_PERSISTENT_MOUNT": mount,
            "TRENDFORGE_STORAGE_RECOVERY_VERIFIED": "false",
            "TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION": "false",
            "TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES": "false",
            "TRENDFORGE_PRODUCTION_RUNTIME": "true",
            "TRENDFORGE_UNIFIED_UI_ENABLED": "true",
            "TRENDFORGE_LIVE_TRADING_ENABLED": "false",
            "TRENDFORGE_PAPER_TRADING_ENABLED": "true",
            "TRENDFORGE_PAPER_AUTO_ENTRY_ENABLED": "true",
            "TRENDFORGE_PAPER_MONITOR_ENABLED": "true",
            "TRENDFORGE_PAPER_MONITOR_INTERVAL_SECONDS": "15",
            "TRENDFORGE_STRATEGY_PAPER_MONITOR_ENABLED": "true",
            "TRENDFORGE_PAPER_TRADING_KILL_SWITCH": "false",
            "TRENDFORGE_TECHNICAL_AUTO_SCAN_ENABLED": "false",
            "FINEDGE_ENABLED": "false",
            "PORT": str(port),
            "WEB_CONCURRENCY": "1",
        }
    )
    os.environ.setdefault("TRENDFORGE_PAPER_MAX_OPEN_POSITIONS", "3")
    os.environ["FUNDAMENTALS_BOOTSTRAP_PATH"] = ""
    _, verified = prepare_storage(root, session_id=session_id)
    os.environ["TRENDFORGE_STORAGE_RECOVERY_VERIFIED"] = str(verified).lower()
    os.environ["TRENDFORGE_ADMIN_API_KEY"] = admin_key(root)
    os.environ["TRENDFORGE_WEBAPP_ACCESS_KEY"] = admin_key(
        root, filename="webapp-key.txt"
    )
    if secrets.compare_digest(
        os.environ["TRENDFORGE_ADMIN_API_KEY"],
        os.environ["TRENDFORGE_WEBAPP_ACCESS_KEY"],
    ):
        raise ValueError("Local webapp and administrative keys must differ")
    return verified


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--port", type=int, default=10000)
    args = parser.parse_args(argv)
    root = Path(args.data_dir).expanduser().resolve()
    phase = "fixed_drive"
    try:
        # Validate the drive before creating directories or starting workers.
        fixed_drive_mount(root)
        phase = "runtime_lock"
        with exclusive_lock(root / "paper-webapp.lock"):
            phase = "configuration"
            verified = configure(root, port=args.port, session_id=secrets.token_hex(16))
            print(f"PC paper webapp: http://127.0.0.1:{args.port}/app/", flush=True)
            print(f"Paper ledger: {root / 'database' / 'trendforge.db'}", flush=True)
            print(f"Sign-in keys are in {root / 'private'} (not printed).", flush=True)
            if not verified:
                print(
                    "First storage probe saved. Stop with Ctrl+C and run this launcher "
                    "again to verify restart recovery.",
                    flush=True,
                )
            else:
                print(
                    "PC storage restart read-back verified. Review paper readiness "
                    "and turn automation ON.",
                    flush=True,
                )
            import uvicorn

            phase = "server_start"
            uvicorn.run("start:app", host="127.0.0.1", port=args.port, workers=1)
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        # Database contents, connection errors or paths can contain private data.
        print(
            f"PC paper startup blocked [{phase}]. Check the local fixed drive, "
            "existing ledger/proof and whether another launcher is running. "
            "Keep the database and proof file intact.",
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
