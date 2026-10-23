"""Opt-in local storage paths; legacy production DATABASE_PATH wins."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

SUBDIRECTORIES = (
    "database",
    "market_data",
    "fundamentals",
    "paper_trading",
    "backtesting",
    "reports",
    "logs",
    "backups",
)


@dataclass(frozen=True)
class StorageConfig:
    root: Path
    database: Path

    def directory(self, name: str) -> Path:
        if name not in SUBDIRECTORIES:
            raise ValueError("Unknown storage directory")
        return self.root / name


def resolve_storage(environ: Mapping[str, str] | None = None) -> StorageConfig:
    env = os.environ if environ is None else environ
    root_value = (env.get("TRENDFORGE_DATA_DIR") or "").strip()
    root = (
        Path(root_value).expanduser().resolve()
        if root_value
        else Path("database").resolve().parent
    )
    explicit_database = (env.get("DATABASE_PATH") or "").strip()
    if explicit_database:
        database = Path(explicit_database).expanduser()
    elif root_value:
        database = root / "database" / "trendforge.db"
    else:
        database = Path("database/trendforge.db")
    return StorageConfig(root=root, database=database)


def initialize_directories(config: StorageConfig, *, create: bool = False) -> list[str]:
    """Explicit opt-in creation; never touches or truncates existing databases."""
    paths = [config.directory(name) for name in SUBDIRECTORIES]
    if create:
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)
    return [str(path) for path in paths]


def _enabled(name: str, default: bool, environ: Mapping[str, str]) -> bool:
    value = environ.get(name)
    return (
        default
        if value is None
        else str(value).strip().lower() in {"1", "true", "yes", "on"}
    )


def production_runtime_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return _enabled(
        "TRENDFORGE_PRODUCTION_RUNTIME", _enabled("RENDER", False, env), env
    )


def storage_health(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """One read-only mount/recovery policy for API and execution services."""
    env = os.environ if environ is None else environ
    configured = bool(
        (env.get("DATABASE_PATH") or "").strip()
        or (env.get("TRENDFORGE_DATA_DIR") or "").strip()
    )
    configured_target = resolve_storage(env).database.expanduser()
    target = configured_target.resolve()
    parent = target.parent
    configured_mount = (env.get("TRENDFORGE_PERSISTENT_MOUNT") or "").strip()
    mount_root = (
        Path(configured_mount).expanduser().resolve()
        if configured_mount and Path(configured_mount).expanduser().is_absolute()
        else None
    )
    unsuitable_mount = bool(
        mount_root
        and (
            mount_root == Path("/")
            or any(
                mount_root.is_relative_to(root)
                for root in (
                    Path("/tmp"),
                    Path("/var/tmp"),
                    Path("/dev"),
                    Path("/proc"),
                    Path("/sys"),
                )
            )
        )
    )
    mount_is_real = bool(
        mount_root and not unsuitable_mount and os.path.ismount(str(mount_root))
    )
    recovery_verified = _enabled("TRENDFORGE_STORAGE_RECOVERY_VERIFIED", False, env)
    target_is_on_mount = bool(
        mount_root and target.is_relative_to(mount_root) and target != mount_root
    )
    verified = bool(
        configured
        and configured_target.is_absolute()
        and mount_is_real
        and target_is_on_mount
        and recovery_verified
    )
    return {
        "status": "persistent" if verified else "ephemeral_or_unverified",
        "database_path": str(target),
        "database_path_configured": configured,
        "database_path_is_absolute": configured_target.is_absolute(),
        "persistent_mount_configured": mount_root is not None,
        "parent": str(parent),
        "parent_is_mountpoint": os.path.ismount(str(parent)),
        "persistent_mount": str(mount_root) if mount_root else None,
        "persistent_mount_is_mountpoint": mount_is_real,
        "database_within_persistent_mount": target_is_on_mount,
        "verified_persistent": verified,
        "restart_recovery_confirmed": recovery_verified,
        "durability_reason": (
            "configured persistent mount is active and restart recovery is operator-confirmed"
            if verified
            else "A configured path is not proof of a persistent disk; verify mount and restart recovery"
        ),
    }


def storage_durability_diagnostics(
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Non-mutating diagnostics using the same verification as paper entry."""
    env = os.environ if environ is None else environ
    config = resolve_storage(env)
    database = config.database.expanduser().resolve()
    health = storage_health(env)
    return {
        "database_path_configured": health["database_path_configured"],
        "database_exists": database.is_file(),
        "database_parent_exists": database.parent.is_dir(),
        "durability_verified": health["verified_persistent"],
        "reason": health["durability_reason"],
    }
