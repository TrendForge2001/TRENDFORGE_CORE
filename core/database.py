"""Canonical SQLite database lifecycle for TrendForge Core."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from database.database import Database
from database.migrations import (
    instruments,
    fundamentals,
    fundamental_field_updates,
    fundamental_field_evidence,
    corporate_actions,
    scanner_results,
    watchlists,
    alerts,
    trade_history,
    portfolio,
    news,
    option_chain,
    settings,
    backtest_results,
    ai_feedback,
)

MIGRATIONS = (
    instruments,
    fundamentals,
    fundamental_field_updates,
    fundamental_field_evidence,
    corporate_actions,
    scanner_results,
    watchlists,
    alerts,
    trade_history,
    portfolio,
    news,
    option_chain,
    settings,
    backtest_results,
    ai_feedback,
)

REQUIRED_TABLES = (
    "instruments",
    "fundamentals",
    "fundamental_field_updates",
    "fundamental_field_evidence",
    "corporate_actions",
    "scanner_results",
    "watchlists",
    "alerts_log",
    "trade_history",
    "portfolio",
    "news",
    "option_chain",
    "settings",
    "backtest_results",
    "ai_feedback",
)


def database_path() -> str:
    return os.getenv("DATABASE_PATH") or "database/trendforge.db"


def database_health(path: str | None = None) -> dict[str, Any]:
    """Validate that the configured SQLite database is usable and initialized."""
    target = path or database_path()
    database_file = Path(target)

    if not database_file.is_file():
        return {
            "status": "not_initialized",
            "path": target,
            "exists": False,
        }

    try:
        with sqlite3.connect(target) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            integrity_status = integrity[0] if integrity else "unknown"
            if integrity_status != "ok":
                return {
                    "status": "degraded",
                    "path": target,
                    "exists": True,
                    "reason": "integrity_check_failed",
                    "integrity_check": integrity_status,
                }

            rows = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            tables = {row[0] for row in rows}
    except (OSError, sqlite3.Error) as exc:
        return {
            "status": "degraded",
            "path": target,
            "exists": True,
            "reason": "database_unreadable",
            "error": str(exc),
        }

    missing_tables = [table for table in REQUIRED_TABLES if table not in tables]
    if missing_tables:
        return {
            "status": "degraded",
            "path": target,
            "exists": True,
            "reason": "schema_incomplete",
            "missing_tables": missing_tables,
            "tables": sorted(tables),
        }

    return {
        "status": "ready",
        "path": target,
        "exists": True,
        "integrity_check": "ok",
        "tables": len(tables),
    }


def initialize_database(path: str | None = None) -> dict[str, Any]:
    target = path or database_path()
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    db = Database(target)
    for migration in MIGRATIONS:
        migration.migrate(db)
    db.close()
    return {
        "status": "initialized",
        "path": target,
        "migrations": len(MIGRATIONS),
    }


__all__ = [
    "database_path",
    "database_health",
    "initialize_database",
    "MIGRATIONS",
    "REQUIRED_TABLES",
]
