"""Contracts for read-only live portfolio synchronization."""
from __future__ import annotations

from types import SimpleNamespace

from services.live_portfolio_sync import LivePortfolioSyncService


class FakeBroker:
    def holdings(self):
        return [{"tradingsymbol": "RELIANCE", "exchange": "NSE", "quantity": 10, "average_price": 1000, "last_price": 1100}]

    def positions(self):
        return [{"tradingsymbol": "RELIANCE", "exchange": "NSE", "quantity": 2, "average_price": 1050, "last_price": 1100}]


class FakeRepository:
    def __init__(self):
        self.rows = []

    def save_many(self, rows):
        self.rows = rows

    def portfolio_value(self):
        return sum(r["quantity"] * r["ltp"] for r in self.rows)

    def investment(self):
        return sum(r["quantity"] * r["average_price"] for r in self.rows)

    def total_pnl(self):
        return self.portfolio_value() - self.investment()

    def all(self):
        return [SimpleNamespace(**r) for r in self.rows]


def test_live_portfolio_sync_merges_holdings_and_positions():
    repo = FakeRepository()
    result = LivePortfolioSyncService(FakeBroker(), repo).sync()
    assert result["count"] == 1
    assert repo.rows[0]["quantity"] == 12
    assert round(repo.rows[0]["average_price"], 2) == 1008.33
    assert result["portfolio_value"] == 13200.0
    assert round(result["total_pnl"], 2) == 1100.0


def test_live_portfolio_sync_does_not_place_orders():
    broker = FakeBroker()
    LivePortfolioSyncService(broker, FakeRepository()).sync()
    assert not hasattr(broker, "place_order")
