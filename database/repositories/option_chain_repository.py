"""Repository for persisted option-chain snapshots."""

from database.database import Database


class OptionChainRepository:
    FIELDS = ("symbol", "expiry", "strike", "option_type", "oi", "oi_change", "volume", "iv", "ltp", "updated_at")

    def __init__(self, db=None):
        self.db = db or Database()

    def save(self, data):
        values = tuple(data.get(field) for field in self.FIELDS)
        placeholders = ", ".join("?" for _ in self.FIELDS)
        self.db.execute(
            "INSERT INTO option_chain (" + ", ".join(self.FIELDS) + ") VALUES (" + placeholders + ")",
            values,
        )

    def latest(self, limit=100):
        return self.db.fetchall("SELECT * FROM option_chain ORDER BY id DESC LIMIT ?", (limit,))
