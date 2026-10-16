from __future__ import annotations

import pandas as pd
import pytest

from services.backtest_service import BacktestService


class FakeRepository:
    def __init__(self):
        self.rows = {}

    def by_run_id(self, run_id):
        return self.rows.get(run_id)

    def save(self, data):
        row = {
            **data,
            "parameters": dict(data.get("parameters") or {}),
            "result": dict(data.get("result") or {}),
        }
        self.rows[data["run_id"]] = row
        return row

    def latest(self, limit=100):
        return list(self.rows.values())[-limit:]

    def by_symbol(self, symbol, limit=100):
        return [
            row
            for row in list(self.rows.values())[-limit:]
            if row.get("symbol") == symbol
        ]

    def count(self):
        return len(self.rows)

    def close(self):
        pass


class FakeMarketData:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def candles(self, symbol, period="2y", interval="1d"):
        self.calls.append((symbol, period, interval))
        return self.frame.copy()

    def begin_observation(self):
        pass

    def observability_snapshot(self, symbols=None):
        return {"provider": "fake", "symbols": list(symbols or [])}

    def health(self):
        return {"status": "runtime_verified"}


class ScriptedIndicators:
    def __init__(self, entry_index=10, exit_index=20):
        self.entry_index = entry_index
        self.exit_index = exit_index

    def calculate(self, frame):
        out = frame.copy()
        out["EMA_20"] = 99.0
        out["EMA_50"] = 100.0
        out["RSI"] = 65.0

        out.loc[
            out.index[self.entry_index: self.exit_index],
            "EMA_20",
        ] = 101.0
        out.loc[
            out.index[self.entry_index: self.exit_index],
            "EMA_50",
        ] = 100.0
        return out


def price_frame():
    dates = pd.date_range(
        "2026-01-01",
        periods=65,
        freq="D",
    )
    opens = [100.0] * 65
    closes = [100.0] * 65

    opens[11] = 102.0
    closes[11] = 103.0
    opens[21] = 110.0
    closes[21] = 109.0
    closes[-1] = 105.0

    return pd.DataFrame(
        {
            "open": opens,
            "high": [value + 1 for value in opens],
            "low": [value - 1 for value in opens],
            "close": closes,
            "volume": [1_000_000] * 65,
        },
        index=dates,
    )


def test_backtest_fills_entry_and_exit_on_next_bar_open():
    repository = FakeRepository()
    service = BacktestService(
        market_data=FakeMarketData(price_frame()),
        repository=repository,
        indicator_engine=ScriptedIndicators(),
    )

    result = service.run(
        symbol="tcs",
        period="1y",
        capital=100000,
        run_id="bt-next-bar",
    )

    assert result["status"] == "completed"
    assert result["symbol"] == "TCS"
    assert result["metrics"]["total_trades"] == 1

    trade = result["trades"][0]
    assert trade["entry_signal_at"].startswith("2026-01-11")
    assert trade["entry_at"].startswith("2026-01-12")
    assert trade["entry_raw_open"] == 102.0
    assert trade["exit_signal_at"].startswith("2026-01-21")
    assert trade["exit_at"].startswith("2026-01-22")
    assert trade["exit_raw_open"] == 110.0
    assert trade["quantity"] == 980
    assert trade["net_pnl"] == 7840.0
    assert result["metrics"]["final_capital"] == 107840.0

    persisted = repository.by_run_id("bt-next-bar")
    assert persisted["result"]["run_id"] == "bt-next-bar"


def test_backtest_costs_and_slippage_reduce_returns():
    service = BacktestService(
        market_data=FakeMarketData(price_frame()),
        repository=FakeRepository(),
        indicator_engine=ScriptedIndicators(),
    )

    frictionless = service.run(
        symbol="TCS",
        period="1y",
        capital=100000,
        run_id="bt-free",
    )
    with_costs = service.run(
        symbol="TCS",
        period="1y",
        capital=100000,
        cost_bps=10,
        slippage_bps=10,
        run_id="bt-costs",
    )

    assert (
        with_costs["metrics"]["net_profit"]
        < frictionless["metrics"]["net_profit"]
    )
    assert with_costs["metrics"]["transaction_costs"] > 0
    assert (
        with_costs["metrics"]["slippage_impact_estimate"]
        > 0
    )


def test_backtest_rejects_duplicate_run_id():
    repository = FakeRepository()
    service = BacktestService(
        market_data=FakeMarketData(price_frame()),
        repository=repository,
        indicator_engine=ScriptedIndicators(),
    )
    service.run(
        symbol="TCS",
        period="1y",
        run_id="bt-duplicate",
    )

    with pytest.raises(ValueError, match="already exists"):
        service.run(
            symbol="TCS",
            period="1y",
            run_id="bt-duplicate",
        )


def test_backtest_history_is_compact_and_detail_is_full():
    repository = FakeRepository()
    service = BacktestService(
        market_data=FakeMarketData(price_frame()),
        repository=repository,
        indicator_engine=ScriptedIndicators(),
    )
    service.run(
        symbol="TCS",
        period="1y",
        run_id="bt-history",
    )

    history = service.history(limit=10)
    assert history["returned"] == 1
    assert "trades" not in history["runs"][0]

    detail = service.get("bt-history")
    assert detail["trades"]
    assert detail["equity_curve"]
    assert detail["safety"]["broker_orders_allowed"] is False
