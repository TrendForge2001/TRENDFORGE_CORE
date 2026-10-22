"""TrendForge SQLite database manager."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from core.storage_config import resolve_storage

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_PATH = "database/trendforge.db"


class Database:
    """Small SQLite boundary shared by repositories and migrations."""

    def __init__(self, db_path: str | None = None):
        self._lock = threading.RLock()
        target = db_path or str(resolve_storage().database)
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = target
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        logger.info("SQLite connected: %s", self.db_path)

    def execute(self, query, params=()):
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(query, params)
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                cur.close()
                raise
            return cur

    def executemany(self, query, values):
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.executemany(query, values)
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                cur.close()
                raise
            return cur

    def fetchall(self, query, params=()):
        with self._lock:
            return self.execute(query, params).fetchall()

    def fetchone(self, query, params=()):
        with self._lock:
            return self.execute(query, params).fetchone()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        with self._lock:
            self.conn.close()
