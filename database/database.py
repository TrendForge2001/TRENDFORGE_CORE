"""TrendForge SQLite database manager."""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_PATH = "database/trendforge.db"


class Database:
    """Small SQLite boundary shared by repositories and migrations."""

    def __init__(self, db_path: str | None = None):
        target = db_path or os.getenv("DATABASE_PATH") or DEFAULT_DATABASE_PATH
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = target
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        logger.info("SQLite connected: %s", self.db_path)

    def execute(self, query, params=()):
        cur = self.conn.cursor()
        cur.execute(query, params)
        self.conn.commit()
        return cur

    def executemany(self, query, values):
        cur = self.conn.cursor()
        cur.executemany(query, values)
        self.conn.commit()
        return cur

    def fetchall(self, query, params=()):
        return self.execute(query, params).fetchall()

    def fetchone(self, query, params=()):
        return self.execute(query, params).fetchone()

    def close(self):
        self.conn.close()
