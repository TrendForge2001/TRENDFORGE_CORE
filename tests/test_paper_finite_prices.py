"""Invalid paper prices must not become fills, marks, closes or serialized P&L."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace

import pytest

from execution.portfolio_manager import PortfolioManager
from services.paper_quote_monitor import PaperQuoteMonitor
from services.paper_trading_runtime import PaperTradingRuntime

NOW = datetime(2026, 10, 23, 10, 0)
NONFINITE = [float("inf"), float("-inf"), float("nan")]


class Trades:
    def __init__(self):
        self.saved = []
        self.closed = []

    def save(self, **kwargs):
        self.saved.append(kwargs)
        return len(self.saved)

    def close_trade(self, trade_id, price, **kwargs):
        self.closed.append((trade_id, price, kwargs))

    def realized_pnl(self):
        return 0.0


def order(symbol="TCS", **overrides):
    values = {
        "symbol": symbol,
        "side": "BUY",
        "quantity": 1,
        "price": 100.0,
        "stoploss": 95.0,
        "target2": 110.0,
    }
    return SimpleNamespace(**{**values, **overrides})


@pytest.mark.parametrize("invalid", [*NONFINITE, "Infinity", "NaN", True, False])
def test_provider_nonfinite_quote_cannot_reach_paper_monitor(invalid):
    calls = []
    paper = SimpleNamespace(
        runtime=SimpleNamespace(portfolio=SimpleNamespace(positions={"TCS": object()})),
        monitor=lambda *args, **kwargs: calls.append(args),
    )
    quotes = SimpleNamespace(
        safe_ltp=lambda symbols: {"NSE:TCS": {"last_price": invalid}}
    )
    monitor = PaperQuoteMonitor(paper, quotes, enabled=True)
    with pytest.raises(RuntimeError, match="Live quote missing"):
        monitor.tick(now=NOW)
    assert calls == []
    assert monitor.quote_success_count == 0
    assert monitor.quote_failure_count == 1
    assert monitor.last_quotes == {}


@pytest.mark.parametrize("invalid", ["nan", "inf", "-inf", "invalid"])
def test_nonfinite_environment_poll_intervals_use_safe_defaults(monkeypatch, invalid):
    monkeypatch.setenv("TRENDFORGE_PAPER_MONITOR_INTERVAL_SECONDS", invalid)
    monkeypatch.setenv("TRENDFORGE_PAPER_MONITOR_IDLE_SECONDS", invalid)
    monitor = PaperQuoteMonitor(None, None)
    assert monitor.poll_interval_seconds == 15.0
    assert monitor.idle_interval_seconds == 30.0


@pytest.mark.parametrize("invalid", NONFINITE)
def test_nonfinite_constructor_intervals_cannot_disable_or_spin_monitor(invalid):
    monitor = PaperQuoteMonitor(
        None, None, poll_interval_seconds=invalid, idle_interval_seconds=invalid
    )
    assert monitor.poll_interval_seconds == 15.0
    assert monitor.idle_interval_seconds == 30.0


@pytest.mark.parametrize("field", ["price", "stoploss", "target2", "quantity"])
@pytest.mark.parametrize("invalid", [*NONFINITE, True, False])
def test_nonfinite_order_rejected_before_persisting_or_adding_position(field, invalid):
    trades = Trades()
    runtime = PaperTradingRuntime(trades=trades)
    with pytest.raises(ValueError, match="finite"):
        runtime.open(order(**{field: invalid}), now=NOW)
    assert trades.saved == []
    assert runtime.portfolio.positions == {}


def test_finite_numbers_with_overflowing_position_value_are_rejected():
    trades = Trades()
    runtime = PaperTradingRuntime(trades=trades)
    with pytest.raises(ValueError, match="position value must be finite"):
        runtime.open(order(price=1e308, quantity=1_000_000), now=NOW)
    assert trades.saved == []
    assert runtime.portfolio.positions == {}


@pytest.mark.parametrize("invalid", NONFINITE)
def test_invalid_existing_ledger_blocks_new_entry_before_persistence(invalid):
    trades = Trades()
    trades.realized_pnl = lambda: invalid
    runtime = PaperTradingRuntime(trades=trades)
    with pytest.raises(ValueError, match="Paper P&L totals must be finite"):
        runtime.open(order(), now=NOW)
    assert trades.saved == []
    assert runtime.portfolio.positions == {}


@pytest.mark.parametrize("invalid", [*NONFINITE, 0.0, -1.0])
def test_invalid_mark_does_not_update_or_close_any_position(invalid):
    trades = Trades()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(order("TCS"), now=NOW)
    runtime.open(order("INFY"), now=NOW)
    with pytest.raises(ValueError, match="finite"):
        runtime.monitor({"TCS": 120.0, "INFY": invalid}, now=NOW)
    assert trades.closed == []
    assert set(runtime.portfolio.positions) == {"TCS", "INFY"}
    assert all(
        position.ltp == 100.0 for position in runtime.portfolio.positions.values()
    )
    assert all(position.pnl == 0.0 for position in runtime.portfolio.positions.values())


@pytest.mark.parametrize("invalid", [*NONFINITE, 0.0, -1.0])
def test_invalid_strategy_exit_never_becomes_a_close(invalid):
    trades = Trades()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(order(strategy_id="test_strategy"), now=NOW)
    with pytest.raises(ValueError, match="finite"):
        runtime.close_strategy_exit("TCS", invalid, exit_signal="SELL", now=NOW)
    assert trades.closed == []
    assert runtime.portfolio.positions["TCS"].ltp == 100.0


@pytest.mark.parametrize(
    "entry,quantity,mark",
    [
        (100.0, 1_000_000, 1e308),
        (1e-300, 1, 1e300),
    ],
)
def test_mark_with_nonfinite_money_or_percentage_is_rejected(entry, quantity, mark):
    trades = Trades()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(order(price=entry, quantity=quantity), now=NOW)
    with pytest.raises(ValueError, match="non-finite P&L"):
        runtime.monitor({"TCS": mark}, now=NOW)
    assert trades.closed == []
    assert runtime.portfolio.positions["TCS"].ltp == entry


def test_optional_nonfinite_scores_do_not_pollute_position_or_ledger_json():
    trades = Trades()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(
        order(strategy_score=float("inf"), consensus_score=float("nan")), now=NOW
    )
    assert trades.saved[0]["strategy_score"] is None
    assert trades.saved[0]["consensus_score"] is None
    snapshot = runtime.snapshot()
    assert snapshot["positions"][0]["strategy_score"] == 0.0
    assert snapshot["positions"][0]["consensus_score"] == 0.0
    json.dumps(snapshot, allow_nan=False)


def test_nonfinite_realized_ledger_raises_safe_error_instead_of_invalid_json():
    trades = Trades()
    trades.realized_pnl = lambda: float("inf")
    runtime = PaperTradingRuntime(trades=trades)
    with pytest.raises(ValueError, match="Paper P&L totals must be finite"):
        runtime.snapshot()


def test_nonfinite_restored_fill_is_not_added_to_portfolio():
    trades = Trades()
    trades.open_trades = lambda: [
        {
            "id": 1,
            "symbol": "TCS",
            "side": "BUY",
            "quantity": 1,
            "entry_price": float("inf"),
            "stoploss": 95.0,
            "target": 110.0,
        }
    ]
    runtime = PaperTradingRuntime(trades=trades)
    with pytest.raises(ValueError, match="entry_price must be finite"):
        runtime.restore_open()
    assert runtime.portfolio.positions == {}


def test_failed_portfolio_admission_never_persists_order_and_preserves_prior_position():
    class RejectingPortfolio(PortfolioManager):
        def add(self, trade):
            super().add(trade)
            if trade.symbol == "INFY":
                raise ValueError("Portfolio admission rejected")

    trades = Trades()
    runtime = PaperTradingRuntime(portfolio=RejectingPortfolio(), trades=trades)
    runtime.open(order(), now=NOW)
    existing = runtime.portfolio.positions["TCS"]

    with pytest.raises(ValueError, match="Portfolio admission rejected"):
        runtime.open(order("INFY"), now=NOW)

    assert [saved["symbol"] for saved in trades.saved] == ["TCS"]
    assert runtime.portfolio.positions == {"TCS": existing}
    assert runtime._trade_ids == {"TCS": 1}


def test_failed_trade_save_removes_only_new_staged_position():
    trades = Trades()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(order(), now=NOW)
    existing = runtime.portfolio.positions["TCS"]

    def save_failed(**kwargs):
        raise RuntimeError("Trade persistence unavailable")

    trades.save = save_failed
    with pytest.raises(RuntimeError, match="Trade persistence unavailable"):
        runtime.open(order("INFY"), now=NOW)

    assert runtime.portfolio.positions == {"TCS": existing}
    assert runtime._trade_ids == {"TCS": 1}


def test_concurrent_same_symbol_entries_commit_once():
    entered = threading.Event()
    release = threading.Event()
    second_started = threading.Event()

    class HeldTrades(Trades):
        def save(self, **kwargs):
            entered.set()
            assert release.wait(3.0)
            return super().save(**kwargs)

    trades = HeldTrades()
    runtime = PaperTradingRuntime(trades=trades)

    def second_open():
        second_started.set()
        return runtime.open(order(), now=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runtime.open, order(), NOW)
        try:
            assert entered.wait(2.0)
            second = pool.submit(second_open)
            assert second_started.wait(2.0)
        finally:
            release.set()
        assert first.result(timeout=3.0) == 1
        with pytest.raises(ValueError, match="already open"):
            second.result(timeout=3.0)

    assert len(trades.saved) == 1
    assert set(runtime.portfolio.positions) == {"TCS"}


def test_concurrent_manual_and_background_marks_close_position_once():
    entered = threading.Event()
    release = threading.Event()
    second_started = threading.Event()

    class HeldTrades(Trades):
        def close_trade(self, trade_id, price, **kwargs):
            entered.set()
            assert release.wait(3.0)
            super().close_trade(trade_id, price, **kwargs)

    trades = HeldTrades()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(order(), now=NOW)

    def second_mark():
        second_started.set()
        return runtime.monitor({"TCS": 120.0}, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runtime.monitor, {"TCS": 120.0}, NOW)
        try:
            assert entered.wait(2.0)
            second = pool.submit(second_mark)
            assert second_started.wait(2.0)
        finally:
            release.set()
        closed = first.result(timeout=3.0) + second.result(timeout=3.0)

    assert len(closed) == 1
    assert len(trades.closed) == 1
    assert runtime.portfolio.positions == {}
    assert runtime._trade_ids == {}


@pytest.mark.parametrize("target_close", [False, True])
def test_aggregate_overflow_rejected_before_any_monitor_mark_or_close(target_close):
    trades = Trades()
    runtime = PaperTradingRuntime(trades=trades)
    symbols = ("TCS", "INFY", "SBIN")
    for symbol in symbols:
        runtime.open(
            order(symbol, stoploss=0.0, target2=110.0 if target_close else 0.0), now=NOW
        )

    with pytest.raises(ValueError, match="Paper P&L totals must be finite"):
        runtime.monitor({symbol: 7e307 for symbol in symbols}, now=NOW)

    assert trades.closed == []
    assert set(runtime.portfolio.positions) == set(symbols)
    assert runtime._trade_ids == {"TCS": 1, "INFY": 2, "SBIN": 3}
    assert all(
        position.ltp == 100.0 for position in runtime.portfolio.positions.values()
    )
    assert all(position.pnl == 0.0 for position in runtime.portfolio.positions.values())


@pytest.mark.parametrize("target_close", [False, True])
def test_monitor_projection_includes_saved_realized_pnl_and_combined_total(
    target_close,
):
    trades = Trades()
    trades.realized_pnl = lambda: 1e308
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(order(stoploss=0.0, target2=110.0 if target_close else 0.0), now=NOW)

    with pytest.raises(ValueError, match="Paper P&L totals must be finite"):
        runtime.monitor({"TCS": 8e307}, now=NOW)

    assert trades.closed == []
    assert runtime.portfolio.positions["TCS"].ltp == 100.0
    assert runtime.portfolio.positions["TCS"].pnl == 0.0


def test_strategy_exit_projection_includes_existing_saved_realized_pnl():
    trades = Trades()
    trades.realized_pnl = lambda: 1e308
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(order(strategy_id="test_strategy"), now=NOW)

    with pytest.raises(ValueError, match="Paper P&L totals must be finite"):
        runtime.close_strategy_exit("TCS", 8e307, exit_signal="SELL", now=NOW)

    assert trades.closed == []
    assert runtime.portfolio.positions["TCS"].ltp == 100.0
    assert runtime.portfolio.positions["TCS"].pnl == 0.0


def test_strategy_exit_validates_combined_remaining_unrealized_and_realized_total():
    trades = Trades()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(order(strategy_id="test_strategy"), now=NOW)
    runtime.open(order("INFY", stoploss=0.0, target2=0.0), now=NOW)
    runtime.portfolio.update("INFY", 1e308)
    assert runtime.snapshot()["total_pnl"] == 1e308

    with pytest.raises(ValueError, match="Paper P&L totals must be finite"):
        runtime.close_strategy_exit("TCS", 1e308, exit_signal="SELL", now=NOW)

    assert trades.closed == []
    assert set(runtime.portfolio.positions) == {"TCS", "INFY"}
    assert runtime.portfolio.positions["TCS"].ltp == 100.0
    assert runtime.portfolio.positions["INFY"].ltp == 1e308


@pytest.mark.parametrize("strategy_exit", [False, True])
def test_invalid_saved_realized_ledger_cannot_be_followed_by_new_mark_or_close(
    strategy_exit,
):
    trades = Trades()
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(order(strategy_id="test_strategy"), now=NOW)
    trades.realized_pnl = lambda: float("inf")

    with pytest.raises(ValueError, match="Paper P&L totals must be finite"):
        if strategy_exit:
            runtime.close_strategy_exit("TCS", 120.0, exit_signal="SELL", now=NOW)
        else:
            runtime.monitor({"TCS": 120.0}, now=NOW)

    assert trades.closed == []
    assert runtime.portfolio.positions["TCS"].ltp == 100.0
    assert runtime.portfolio.positions["TCS"].pnl == 0.0


def test_large_finite_balances_are_admitted_without_an_arbitrary_price_ceiling():
    trades = Trades()
    trades.realized_pnl = lambda: 7e307
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(order(), now=NOW)
    closed = runtime.monitor({"TCS": 1e308}, now=NOW)
    assert closed[0]["exit_price"] == 1e308
    assert closed[0]["pnl"] == 1e308
    assert len(trades.closed) == 1


@pytest.mark.parametrize(
    "saved_realized,should_close", [(-1e308, False), (1e308, True)]
)
def test_aggregate_projection_uses_short_pnl_direction(saved_realized, should_close):
    trades = Trades()
    trades.realized_pnl = lambda: saved_realized
    runtime = PaperTradingRuntime(trades=trades)
    runtime.open(order(side="SHORT", stoploss=110.0, target2=95.0), now=NOW)

    if should_close:
        closed = runtime.monitor({"TCS": 8e307}, now=NOW)
        assert closed[0]["pnl"] == -8e307
        assert len(trades.closed) == 1
    else:
        with pytest.raises(ValueError, match="Paper P&L totals must be finite"):
            runtime.monitor({"TCS": 8e307}, now=NOW)
        assert trades.closed == []
        assert runtime.portfolio.positions["TCS"].ltp == 100.0
