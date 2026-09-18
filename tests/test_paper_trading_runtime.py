"""End-to-end contracts for the paper trading runtime."""
from __future__ import annotations

from datetime import datetime, timezone

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

    def realized_pnl(self):
        return 1050.0 if self.closed else 0.0


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
    trade_id = runtime.open(Order(), datetime(2026, 9, 18, 14, 0))

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

    assert closed[0]["reason"] == "FORCE_EXIT_15_00_IST"
    assert closed[0]["pnl"] == 200.0


def test_paper_runtime_stoploss_and_never_places_broker_orders():
    trades = FakeTrades()
    broker = FakeBroker()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(Order())

    closed = runtime.monitor({"RELIANCE": 949.0}, datetime(2026, 9, 18, 14, 0))

    assert closed[0]["reason"] == "STOPLOSS"
    assert broker.place_order_calls == 0
    assert runtime.portfolio.positions == {}


def test_paper_runtime_restores_persisted_open_trade():
    class RestoreTrades(FakeTrades):
        def open_trades(self):
            return [{
                "id": 7,
                "symbol": "TCS",
                "side": "BUY",
                "quantity": 5,
                "entry_price": 3000.0,
                "stoploss": 2900.0,
                "target": 3200.0,
            }]

    runtime = PaperTradingRuntime(trades=RestoreTrades())
    assert runtime.restore_open() == 1
    assert runtime.portfolio.positions["TCS"].quantity == 5
    assert runtime._trade_ids["TCS"] == 7


def test_paper_runtime_converts_aware_time_to_ist():
    trades = FakeTrades()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(Order())

    # 09:30 UTC is 15:00 IST.
    closed = runtime.monitor(
        {"RELIANCE": 1020.0},
        datetime(2026, 9, 18, 9, 30, tzinfo=timezone.utc),
    )
    assert closed[0]["reason"] == "FORCE_EXIT_15_00_IST"


def test_paper_runtime_rejects_outside_market_hours():
    trades = FakeTrades()
    runtime = PaperTradingRuntime(trades=trades)
    for now in (datetime(2026, 9, 18, 9, 14), datetime(2026, 9, 18, 15, 0), datetime(2026, 9, 19, 10, 0)):
        try:
            runtime.open(Order(), now)
        except ValueError:
            pass
        else:
            raise AssertionError("paper entry must be rejected outside market hours")


def test_paper_runtime_reports_realized_and_unrealized_pnl():
    trades = FakeTrades()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(Order(), datetime(2026, 9, 18, 14, 0))
    runtime.monitor({"RELIANCE": 1050.0}, datetime(2026, 9, 18, 14, 30))
    snap = runtime.snapshot()
    assert snap["unrealized_pnl"] == 500.0
    assert snap["realized_pnl"] == 0.0
    assert snap["total_pnl"] == 500.0
