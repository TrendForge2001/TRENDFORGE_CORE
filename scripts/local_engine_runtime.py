"""R70.2 Windows local runtime. Fail-closed observer: no orders or automatic scans.

The runtime owns no web endpoints, does not log credentials and does not modify
Render configuration.  Kite session checks and bounded scans require explicit
CLI actions.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time

from core.database import database_health

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def paths(root: str | None = None, db: str | None = None) -> tuple[Path, Path]:
    folder = root or os.environ.get("TRENDFORGE_DATA_DIR", "")
    database = db or os.environ.get("DATABASE_PATH", "")
    if not folder or not database:
        raise ValueError("Both TRENDFORGE_DATA_DIR and DATABASE_PATH are required")
    location = Path(folder).expanduser().resolve()
    target = Path(database).expanduser().resolve()
    if target != location / "database" / "trendforge.db":
        raise ValueError("Database must be C:\\TrendForgeData\\database\\trendforge.db relative to configured data root")
    return location, target


def preflight(root: str | None = None, db: str | None = None) -> dict:
    try:
        location, target = paths(root, db)
    except ValueError as exc:
        return {"status": "blocked", "reason": str(exc)}
    if not location.is_dir():
        return {"status": "blocked", "reason": "data_root_missing"}
    health = database_health(str(target))
    return {
        "status": "ready" if health.get("status") == "ready" else "blocked",
        "database": str(target),
        "data_root": str(location),
        "schema": health.get("status"),
        "tables": health.get("tables"),
        "integrity": health.get("integrity_check"),
        "mode": "observe_only",
        "live_orders_enabled": False,
        "paper_orders_enabled": False,
        "automatic_scanning_enabled": False,
    }


def verify_kite_session() -> dict:
    """Only called on explicit --kite-check; performs a real authenticated API call."""
    key = os.getenv("KITE_API_KEY")
    token = os.getenv("KITE_ACCESS_TOKEN")
    if not key or not token:
        return {"status": "not_authenticated", "reason": "kite_key_or_access_token_missing"}
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=key)
        kite.set_access_token(token)
        profile = kite.profile()
        if not isinstance(profile, dict):
            return {"status": "failed", "reason": "unexpected_profile_response"}
        return {"status": "authenticated", "source": "kite_profile"}
    except Exception as exc:
        # Do not place potentially sensitive exception text in logs.
        return {"status": "failed", "reason": type(exc).__name__}


@contextmanager
def exclusive_lock(path: Path):
    """Interprocess lock, released when the process exits (including crashes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Local engine already running") from exc
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("Local engine already running") from exc
        locked = True
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode("ascii"))
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def stop(root: str | None = None, db: str | None = None) -> dict:
    location, _ = paths(root, db)
    if not (location / "logs" / "local_engine.lock").exists():
        return {"status": "not_started"}
    marker = location / "logs" / "local_engine.stop"
    write_status(marker, {"requested_at_utc": datetime.now(timezone.utc).isoformat()})
    return {"status": "stop_requested"}


def run(interval: int = 60, *, now=None, sleep=time.sleep) -> dict:
    """Observer process. Never starts API, scheduler, scanner or order engine."""
    health = preflight()
    if health["status"] != "ready":
        return health
    root, _ = paths()
    logs = root / "logs"
    status_path = logs / "local_engine_status.json"
    stop_path = logs / "local_engine.stop"
    with exclusive_lock(logs / "local_engine.lock"):
        stop_path.unlink(missing_ok=True)  # stale signal from an earlier session
        while True:
            current = (now() if now else datetime.now(IST)).astimezone(IST)
            if stop_path.exists():
                status = "stopped"
            elif current.weekday() >= 5:
                status = "non_trading_weekend"
            elif current.hour >= 16:
                status = "market_day_window_complete"
            else:
                status = "observing"
            payload = {
                "status": status,
                "time_ist": current.isoformat(),
                "mode": "observe_only",
                "market_calendar": "not_verified",
                "kite_session": "not_checked",
                "automatic_scanning_enabled": False,
                "paper_orders_enabled": False,
                "live_orders_enabled": False,
                "database_status": "ready",
            }
            write_status(status_path, payload)
            if status != "observing":
                stop_path.unlink(missing_ok=True)
                return payload
            sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TrendForge R70.2 PC runtime")
    parser.add_argument("command", choices=("preflight", "run", "stop", "kite-check"))
    parser.add_argument("--root", default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args(argv)

    if args.command == "preflight":
        result = preflight(args.root, args.db)
    elif args.command == "kite-check":
        result = preflight(args.root, args.db)
        if result["status"] == "ready":
            result["kite"] = verify_kite_session()
            if result["kite"]["status"] != "authenticated":
                result["status"] = "blocked"
    elif args.command == "stop":
        try:
            result = stop(args.root, args.db)
        except ValueError as exc:
            result = {"status": "blocked", "reason": str(exc)}
    else:
        if args.interval < 10 or args.interval > 900:
            parser.error("--interval must be from 10 to 900 seconds")
        result = run(interval=args.interval)
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
