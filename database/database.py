"""TrendForge SQLite database manager."""
from __future__ import annotations
import logging, os, sqlite3
from pathlib import Path
logger=logging.getLogger(__name__)
class Database:
    def __init__(self, db_path=None):
        configured=db_path or os.getenv("TRENDFORGE_DB_PATH")
        self.db_path=str(configured or Path("database")/"trendforge.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn=sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory=sqlite3.Row
    def execute(self, query, params=()):
        cur=self.conn.cursor()
        try:
            cur.execute(query, params); self.conn.commit(); return cur
        except Exception:
            self.conn.rollback(); raise
    def executemany(self, query, values):
        cur=self.conn.cursor()
        try:
            cur.executemany(query, values); self.conn.commit(); return cur
        except Exception:
            self.conn.rollback(); raise
    def fetchall(self, query, params=()):
        cur=self.conn.cursor(); cur.execute(query, params); return cur.fetchall()
    def fetchone(self, query, params=()):
        cur=self.conn.cursor(); cur.execute(query, params); return cur.fetchone()
    def close(self): self.conn.close()
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): self.close()
