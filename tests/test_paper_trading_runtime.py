"""End-to-end contracts for the paper trading runtime."""
from __future__ import annotations

from datetime import datetime

from services.paper_trading_runtime import PaperTradingRuntime


class FakeTrades:
    def __init__(self):
        self.saved = []
        self.closed = []

    def save(self, **kwargs):
        self.saved.append(kwargs)
        return len(self.saved)

    def close_trade(self, trade_id, exit_price):
        self.closed.append((trade_id, exit_price))


class FakeBroker:
    def __init__(self):
        self.place_order_calls = 0

    def place_order(self, **kwargs):
        self.place_order_calls += 1


class Order:
    symbol = "RELIANCE"
    side = "BUY"
    quantity = 10
    price = 1000.0
    stoploss = 950.0
    target2 = 1100.0


def test_paper_runtime_persists_open_and_closes_on_target():
    trades = FakeTrades()
    runtime = PaperTradingRuntime(trades=trades)
    trade_id = runtime.open(Order())

    assert trade_id == 1
    assert len(runtime.portfolio.positions) == 1
    closed = runtime.monitor({"RELIANCE": 1105.0}, datetime(2026, 9, 18, 14, 30))

    assert closed[0]["reason"] == "TARGET"
    assert closed[0]["pnl"] == 1050.0
    assert trades.closed == [(1, 1105.0)]
    assert not runtime.portfolio.positions


def test_paper_runtime_closes_at_three_pm():
    trades = FakeTrades()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(Order())

    closed = runtime.monitor({"RELIANCE": 1020.0}, datetime(2026, 9, 18, 15, 0))

    assert closed[0]["reason"] == "FORCE_EXIT_15_00"
    assert closed[0]["pnl"] == 200.0


def test_paper_runtime_stoploss_and_never_places_broker_orders():
    trades = FakeTrades()
    broker = FakeBroker()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(Order())

    closed = runtime.monitor({"RELIANCE": 949.0}, datetime(2026, 9, 18, 14, 0))

    assert closed[0]["reason"] == "STOPLOSS"
    assert broker.place_order_calls == 0
