"""Canonical SQLite database lifecycle for TrendForge Core."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from database.database import Database
from database.migrations import (
    instruments, fundamentals, corporate_actions, scanner_results,
    watchlists, alerts, trade_history, portfolio, news, option_chain,
    settings, backtest_results, ai_feedback,
)
MIGRATIONS = (
    instruments, fundamentals, corporate_actions, scanner_results,
    watchlists, alerts, trade_history, portfolio, news, option_chain,
    settings, backtest_results, ai_feedback,
)
def database_path() -> str:
    return os.getenv("DATABASE_PATH") or "database/trendforge.db"
def database_health(path: str | None = None) -> dict[str, Any]:
    target = path or database_path()
    exists = Path(target).is_file()
    return {"status": "ready" if exists else "not_initialized", "path": target, "exists": exists}

def initialize_database(path: str | None = None) -> dict[str, Any]:
    target = path or database_path()
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    db = Database(target)
    for migration in MIGRATIONS:
        migration.migrate(db)
    db.close()
    return {"status": "initialized", "path": target, "migrations": len(MIGRATIONS)}
__all__ = ["database_path", "database_health", "initialize_database", "MIGRATIONS"]
