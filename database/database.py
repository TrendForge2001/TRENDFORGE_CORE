"""
TrendForge
SQLite Database Manager
"""

from pathlib import Path
import sqlite3
import logging

logger = logging.getLogger(__name__)


class Database:

    def __init__(self, db_path: str | None = None):

        target = db_path or "database/trendforge.db"
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = target

        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
        )

        self.conn.row_factory = sqlite3.Row

        logger.info(
            "SQLite connected."
        )

    def execute(
        self,
        query,
        params=(),
    ):

        cur = self.conn.cursor()

        cur.execute(
            query,
            params,
        )

        self.conn.commit()

        return cur

    def executemany(
        self,
        query,
        values,
    ):

        cur = self.conn.cursor()

        cur.executemany(
            query,
            values,
        )

        self.conn.commit()

        return cur

    def fetchall(
        self,
        query,
        params=(),
    ):

        return self.execute(
            query,
            params,
        ).fetchall()

    def fetchone(
        self,
        query,
        params=(),
    ):

        return self.execute(
            query,
            params,
        ).fetchone()

    def close(self):

        self.conn.close()