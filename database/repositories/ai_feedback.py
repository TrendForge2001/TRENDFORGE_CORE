"""Repository for persisted AI feedback records."""
from database.database import Database
class AIFeedbackRepository:
    def __init__(self, db=None): self.db=db or Database()
    def save(self,data):
        self.db.execute("""INSERT INTO ai_feedback (symbol,scanner,signal,score,entry_price,exit_price,outcome,pnl,feedback_date) VALUES (?,?,?,?,?,?,?,?,?)""",(data.get("symbol"),data.get("scanner"),data.get("signal"),data.get("score"),data.get("entry_price"),data.get("exit_price"),data.get("outcome"),data.get("pnl"),data.get("feedback_date")))
    def latest(self,limit=100):
        return self.db.fetchall("SELECT * FROM ai_feedback ORDER BY id DESC LIMIT ?",(limit,))
