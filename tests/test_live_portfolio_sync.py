"""Contracts for read-only live portfolio synchronization."""
from __future__ import annotations
from services.live_portfolio_sync import LivePortfolioSyncService

class FakeBroker:
    def holdings(self):
        return [{"tradingsymbol":"RELIANCE","exchange":"NSE","quantity":10,"average_price":1000,"last_price":1100}]
    def positions(self):
        return [{"tradingsymbol":"RELIANCE","exchange":"NSE","quantity":2,"average_price":1050,"last_price":1100,"product":"MIS"}]

class FakeRepository:
    def __init__(self): self.rows=[]
    def replace_all(self, rows): self.rows=[dict(r) for r in rows]
    def by_book(self, book): return [r for r in self.rows if r["book"]==book]
    def all(self): return self.rows
    def portfolio_value(self): return sum(abs(r["quantity"])*r["ltp"] for r in self.rows)
    def investment(self): return sum(abs(r["quantity"])*r["average_price"] for r in self.rows)
    def total_pnl(self): return sum((r["ltp"]-r["average_price"])*abs(r["quantity"]) if r["quantity"] >= 0 else (r["average_price"]-r["ltp"])*abs(r["quantity"]) for r in self.rows)

def test_live_portfolio_sync_preserves_separate_books():
    repo=FakeRepository(); result=LivePortfolioSyncService(FakeBroker(),repo).sync()
    assert result["count"]==2
    assert len(repo.by_book("HOLDING"))==1
    assert len(repo.by_book("POSITION"))==1
    assert repo.by_book("HOLDING")[0]["quantity"]==10
    assert repo.by_book("POSITION")[0]["quantity"]==2
    assert result["portfolio_value"]==13200.0
    assert result["total_pnl"]==1100.0

def test_live_portfolio_sync_does_not_place_orders():
    broker=FakeBroker(); LivePortfolioSyncService(broker,FakeRepository()).sync()
    assert not hasattr(broker,"place_order")
