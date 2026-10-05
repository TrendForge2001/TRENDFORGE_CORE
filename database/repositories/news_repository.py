"""TrendForge news repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from database.database import Database


class NewsRepository:
    """Persistence adapter for the ``news`` table."""

    def __init__(self, db: Database | None = None):
        self.db = db or Database()

    def insert_news(
        self,
        symbol: str,
        title: str,
        source: str | None = None,
        publisher: str | None = None,
        sentiment: float | str | None = None,
        score: float | None = None,
        published: Any = None,
        url: str | None = None,
        exchange: str = "NSE",
        summary: str | None = None,
        category: str | None = None,
    ):
        """Insert a normalized news item using the current migration schema."""
        self.db.execute(
            """
            INSERT INTO news (
                symbol, exchange, headline, summary, source, url,
                category, sentiment, impact_score, published_at, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol, exchange, title, summary, source or publisher, url,
                category, self._numeric_sentiment(sentiment), score or 0,
                published, datetime.now(),
            ),
        )

    @staticmethod
    def _numeric_sentiment(value: float | str | None) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        normalized = str(value).strip().lower()
        return {"positive": 1.0, "negative": -1.0, "neutral": 0.0}.get(normalized, 0.0)

    def get_by_symbol(self, symbol: str, limit: int = 50):
        return self.db.fetchall(
            """
            SELECT * FROM news
            WHERE symbol=?
            ORDER BY published_at DESC, id DESC
            LIMIT ?
            """,
            (symbol, limit),
        )

    def get_latest(self, symbol: str, limit: int = 20):
        return self.get_by_symbol(symbol, limit)

    def get_all(self, limit: int = 100):
        return self.db.fetchall(
            """
            SELECT * FROM news
            ORDER BY published_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )

    def delete_by_symbol(self, symbol: str):
        self.db.execute("DELETE FROM news WHERE symbol=?", (symbol,))

    def clear(self):
        self.db.execute("DELETE FROM news")
