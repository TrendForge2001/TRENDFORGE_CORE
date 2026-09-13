"""Repository for persisted backtest summaries."""
from database.database import Database
class BacktestResultsRepository:
    FIELDS=("strategy_name","symbol","timeframe","start_date","end_date","total_trades","win_rate","net_profit","max_drawdown","sharpe_ratio","created_at")
    def __init__(self, db=None): self.db=db or Database()
    def save(self,data):
        values=tuple(data.get(field) for field in self.FIELDS)
        self.db.execute("INSERT INTO backtest_results ("+", ".join(self.FIELDS)+") VALUES ("+", ".join("?" for _ in self.FIELDS)+")",values)
    def latest(self,limit=100):
        return self.db.fetchall("SELECT * FROM backtest_results ORDER BY id DESC LIMIT ?",(limit,))
