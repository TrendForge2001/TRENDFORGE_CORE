"""Persistence for broker portfolio books without collapsing holdings and positions."""
from datetime import datetime
from database.database import Database

class LivePortfolioRepository:
    def __init__(self, db=None):
        self.db = db or Database()

    def replace_all(self, rows):
        self.db.execute("DELETE FROM live_portfolio")
        for row in rows:
            self.save(row)

    def save(self, row):
        q = int(row["quantity"])
        avg = float(row["average_price"])
        ltp = float(row["ltp"])
        units = abs(q)
        investment = units * avg
        current = units * ltp
        pnl = (ltp - avg) * units if q >= 0 else (avg - ltp) * units
        self.db.execute(
            """INSERT INTO live_portfolio
            (symbol,exchange,sector,book,product,quantity,average_price,ltp,investment,current_value,pnl,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,exchange,book,product) DO UPDATE SET
              sector=excluded.sector, quantity=excluded.quantity,
              average_price=excluded.average_price, ltp=excluded.ltp,
              investment=excluded.investment, current_value=excluded.current_value,
              pnl=excluded.pnl, updated_at=excluded.updated_at""",
            (str(row["symbol"]).upper(), row.get("exchange","NSE"), row.get("sector"),
             row["book"], row.get("product"), q, avg, ltp, investment, current,
             pnl, datetime.now()),
        )

    def all(self):
        return self.db.fetchall("SELECT * FROM live_portfolio ORDER BY current_value DESC")

    def by_book(self, book):
        return self.db.fetchall("SELECT * FROM live_portfolio WHERE book=? ORDER BY current_value DESC", (book,))

    def portfolio_value(self):
        row = self.db.fetchone("SELECT COALESCE(SUM(current_value),0) total FROM live_portfolio")
        return float(row["total"])

    def investment(self):
        row = self.db.fetchone("SELECT COALESCE(SUM(investment),0) total FROM live_portfolio")
        return float(row["total"])

    def total_pnl(self):
        row = self.db.fetchone("SELECT COALESCE(SUM(pnl),0) total FROM live_portfolio")
        return float(row["total"])

    def close(self):
        self.db.close()
