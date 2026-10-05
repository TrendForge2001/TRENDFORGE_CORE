"""Repository for persisted AI feedback records."""

from database.database import Database


class AIFeedbackRepository:
    FIELDS = ("symbol", "scanner", "signal", "score", "entry_price", "exit_price", "outcome", "pnl", "feedback_date")

    def __init__(self, db=None):
        self.db = db or Database()

    def save(self, data):
        values = tuple(data.get(field) for field in self.FIELDS)
        placeholders = ", ".join("?" for _ in self.FIELDS)
        self.db.execute(
            "INSERT INTO ai_feedback (" + ", ".join(self.FIELDS) + ") VALUES (" + placeholders + ")",
            values,
        )

    def latest(self, limit=100):
        return self.db.fetchall("SELECT * FROM ai_feedback ORDER BY id DESC LIMIT ?", (limit,))
