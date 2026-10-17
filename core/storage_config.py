"""Opt-in local storage paths; legacy production DATABASE_PATH wins."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SUBDIRECTORIES = ("database", "market_data", "fundamentals", "paper_trading",
                  "backtesting", "reports", "logs", "backups")


@dataclass(frozen=True)
class StorageConfig:
    root: Path
    database: Path

    def directory(self, name: str) -> Path:
        if name not in SUBDIRECTORIES:
            raise ValueError("Unknown storage directory")
        return self.root / name


def resolve_storage(environ: dict[str, str] | None = None) -> StorageConfig:
    env = os.environ if environ is None else environ
    root_value = (env.get("TRENDFORGE_DATA_DIR") or "").strip()
    root = Path(root_value).expanduser().resolve() if root_value else Path("database").resolve().parent
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
