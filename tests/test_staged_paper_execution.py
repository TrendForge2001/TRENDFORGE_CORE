"""Real SQLite paper admission, trigger expiry, partial exits and recovery."""

import asyncio
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from core.database import initialize_database
from database.repositories.strategy_runtime_state_repository import (
    StrategyRuntimeStateRepository,
)
from database.repositories.trade_repository import TradeRepository
from providers.kite_paper_quotes import FreshKitePaperQuotes
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from scanner.multi_strategy_engine import MultiStrategyEngine
from scanner.strategy_registry import REGISTRY_VERSION
from services.paper_auto_entry_service import PaperAutoEntryService
from services.paper_trading_runtime import PaperTradingRuntime
from services.paper_trading_service import PaperTradingService
from services.staged_paper_execution import StagedPaperExecution
from services.strategy_paper_automation import StrategyPaperAutomation
from services.strategy_paper_reporting import StrategyPaperReporting
from tests.test_ema_pivot_scanners import IDS, signal_frame

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 2, 10, 15, tzinfo=TZ)


def environment(tmp_path, monkeypatch, key=IDS[0], *, mode="intraday", borrow=True):
    path = str(tmp_path / "paper.db")
    monkeypatch.setenv("DATABASE_PATH", path)
    initialize_database()
    runtime = PaperTradingRuntime(trades=TradeRepository())
    paper = PaperTradingService(runtime, enabled=True, environment_kill_switch=False)
    # Explicit verified-storage fixture; production storage verification remains
    # authoritative and is tested independently by the full release suite.
    monkeypatch.setattr(
        paper,
        "entry_storage_policy",
        lambda: {"mode": "durable", "entry_allowed": True, "verified_persistent": True},
    )
    auto = PaperAutoEntryService(paper, enabled=True)
    clock = SimpleNamespace(now=NOW, price=100.0, age=0)
    quotes = FreshKitePaperQuotes(
        SimpleNamespace(
            quote=lambda instruments: {
                s: {
                    "last_price": clock.price,
                    "timestamp": clock.now - timedelta(seconds=clock.age),
                }
                for s in instruments
            }
        )
    )
    repository = StrategyRuntimeStateRepository()
    frame = signal_frame(key, mode="intraday" if mode == "intraday" else "swing")
    frame.index = (
        pd.DatetimeIndex(["2026-11-02 09:45", "2026-11-02 10:00"], tz=TZ)
        if mode == "intraday"
        else pd.DatetimeIndex(["2026-10-29", "2026-10-30"], tz=TZ)
    )
    evaluation = MultiStrategyEngine().evaluate(
        frame,
        mode=mode,
        interval="15m" if mode == "intraday" else "1d",
        strategy_ids=[key],
    )
    assert evaluation["evaluations"][0]["entry_state"] == "ARMED"
    scan = {
        "status": "completed",
        "run_id": "controlled-scan",
        "mode": mode,
        "universe": "NIFTY 500",
        "requested_symbols": 1,
        "completed_symbols": 1,
        "error_symbols": 0,
        "strategy_ids": [key],
        "top_picks": [
            {
                "symbol": "TCS",
                "bar_at": frame.index[-1].isoformat(),
                "consensus": evaluation["consensus"],
                "consensus_score": evaluation["consensus_score"],
                "strategy_evaluations": evaluation["evaluations"],
            }
        ],
    }
    validation = {
        "status": "completed",
        "run_id": "controlled-pass",
        "registry_version": REGISTRY_VERSION,
        "request": {
            "universes": ["NIFTY 500"],
            "source": "all",
            "modes": ["intraday", "swing", "positional"],
        },
        "strategy_validation": [
            {
                "strategy_id": key,
                "mode": mode,
                "registry_paper_eligible": True,
                "promotion_status": "ELIGIBLE_FOR_REVIEW",
                "universe_gates": [{"universe": "NIFTY 500", "status": "PASS"}],
            }
        ],
    }
    executor = StagedPaperExecution(auto, repository, quotes)
    executor.arm(scan, validation, [key], short_borrow_assumed=borrow, now=clock.now)
    return SimpleNamespace(
        path=path,
        paper=paper,
        runtime=runtime,
        auto=auto,
        clock=clock,
        quotes=quotes,
        repository=repository,
        executor=executor,
        validation=validation,
        scan=scan,
        key=key,
    )


def fill(env):
    risk = env.scan["top_picks"][0]["strategy_evaluations"][0]["risk"]
    env.clock.price = risk["entry_trigger"] + EMA_PIVOT_SETUPS[env.key].direction * 0.05
    result = env.executor.process(
        now=env.clock.now, validation=env.validation, admission_guard=lambda c: True
    )
    assert result["opened_count"] == 1, result
    return env.runtime.portfolio.positions["TCS"]


@pytest.mark.parametrize("key", IDS)
def test_all_eight_wait_for_trigger_then_partial_and_recover_without_duplicate(
    tmp_path, monkeypatch, key
):
    env = environment(tmp_path, monkeypatch, key)
    waiting = env.executor.process(
        now=env.clock.now, validation=env.validation, admission_guard=lambda c: True
    )
    assert (
        waiting["opened_count"] == 0 and env.runtime.snapshot()["open_positions"] == 0
    )
    position = fill(env)
    initial_qty = position.quantity
    assert initial_qty * abs(position.average_price - position.stoploss) <= 500 + 1e-6
    partial_price = position.paper_plan["partial_target"]
    result = env.paper.monitor({"TCS": partial_price}, now=NOW + timedelta(seconds=15))
    assert result["closed"][0]["partial"] is True
    assert position.quantity == initial_qty - initial_qty // 2
    env.paper.monitor({"TCS": partial_price}, now=NOW + timedelta(seconds=30))
    assert len(env.runtime.trades.closed_trades()) == 1
    snapshot = env.runtime.snapshot()
    recovered = PaperTradingRuntime(trades=TradeRepository())
    assert recovered.restore_open() == 1
    restored = recovered.portfolio.positions["TCS"]
    assert (
        restored.paper_plan["partial_taken"] is True
        and restored.quantity == position.quantity
    )
    assert restored.stoploss == position.stoploss
    setup = EMA_PIVOT_SETUPS[key]
    if setup.trailing:
        close = partial_price + setup.direction * 2
        recovered.update_staged_candle(
            "TCS",
            {"close": close, "ATR_WILDER_14": 0.5},
            bar_at="2026-11-02T10:15:00+05:30",
        )
        stop = restored.stoploss
        recovered.update_staged_candle(
            "TCS",
            {"close": close, "ATR_WILDER_14": 10},
            bar_at="2026-11-02T10:30:00+05:30",
        )
        assert restored.stoploss == stop
        exit_price = stop
    else:
        assert restored.stoploss == restored.average_price
        exit_price = restored.target2
    closed = recovered.monitor({"TCS": exit_price}, now=NOW + timedelta(minutes=30))
    assert closed and recovered.snapshot()["open_positions"] == 0
    assert len(recovered.trades.closed_trades()) == 2
    assert recovered.snapshot()["realized_pnl"] == pytest.approx(
        sum(row["pnl"] for row in recovered.trades.closed_trades())
    )
    assert snapshot["total_pnl"] == pytest.approx(
        (partial_price - position.average_price) * initial_qty * setup.direction
    )


@pytest.mark.parametrize("key", IDS)
def test_daily_staged_positions_do_not_force_exit_at_1500(tmp_path, monkeypatch, key):
    mode = "positional" if EMA_PIVOT_SETUPS[key].slow == 200 else "swing"
    env = environment(tmp_path, monkeypatch, key, mode=mode)
    position = fill(env)
    env.paper.monitor({"TCS": position.average_price}, now=NOW.replace(hour=15))
    assert env.runtime.snapshot()["open_positions"] == 1


@pytest.mark.parametrize(
    "damage", ["expiry", "stale_quote", "validation", "stop", "storage", "kill", "gap"]
)
def test_new_paper_entries_remain_fail_closed(tmp_path, monkeypatch, damage):
    env = environment(tmp_path, monkeypatch)
    risk = env.scan["top_picks"][0]["strategy_evaluations"][0]["risk"]
    env.clock.price = risk["entry_trigger"] + 0.05

    def guard(candidate):
        return damage != "stop"

    if damage == "expiry":
        env.clock.now += timedelta(minutes=15)
    elif damage == "stale_quote":
        env.clock.age = 61
    elif damage == "validation":
        env.validation["strategy_validation"][0]["promotion_status"] = "BLOCKED"
    elif damage == "storage":
        monkeypatch.setattr(
            env.paper,
            "entry_storage_policy",
            lambda: {"entry_allowed": False, "message": "Unverified"},
        )
    elif damage == "kill":
        env.paper.set_runtime_kill_switch(True)
    elif damage == "gap":
        env.executor.pending[next(iter(env.executor.pending))]["risk"]["pivot_levels"][
            "R1"
        ] = 107
        env.clock.price = 106
    try:
        env.executor.process(
            now=env.clock.now, validation=env.validation, admission_guard=guard
        )
    except ValueError:
        assert damage == "stale_quote"
    assert env.runtime.snapshot()["open_positions"] == 0
    assert env.runtime.trades.count() == 0


def test_partial_exit_is_atomic_when_database_rejects_child_fill(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    position = fill(env)
    quantity, stop = position.quantity, position.stoploss
    env.runtime.trades.db.execute(
        "CREATE TRIGGER deny_partial BEFORE INSERT ON trade_history "
        "WHEN NEW.parent_trade_id IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT, 'test write failure'); END"
    )
    with pytest.raises(Exception, match="test write failure"):
        env.paper.monitor({"TCS": position.paper_plan["partial_target"]}, now=NOW)
    assert position.quantity == quantity and position.stoploss == stop
    assert position.paper_plan["partial_taken"] is False
    assert env.runtime.trades.open_trades()[0]["quantity"] == quantity
    assert env.runtime.trades.closed_trades() == []


def test_automation_fills_later_in_the_same_candle_and_stop_cancels_pending(
    tmp_path, monkeypatch
):
    env = environment(tmp_path, monkeypatch)
    scanner = SimpleNamespace(
        scan=lambda **kwargs: {**env.scan, "run_id": kwargs["run_id"]}
    )
    service = StrategyPaperAutomation(
        scanner=scanner,
        bridge=SimpleNamespace(
            paper_auto_entry=env.auto, SUPPORTED_MODES={"intraday", "swing"}
        ),
        repository=env.repository,
        quote_provider=env.quotes,
        paper_monitor=SimpleNamespace(tick=lambda **k: None),
        strategy_monitor=SimpleNamespace(tick=lambda **k: None),
        validation_getter=lambda: env.validation,
        validation_starter=lambda **k: None,
        clock=lambda: env.clock.now,
    )
    service.configure(True, strategy_ids=[env.key])
    service.tick()
    assert service.staged.pending and env.runtime.snapshot()["open_positions"] == 0
    env.clock.now += timedelta(seconds=15)
    env.clock.price = 103.1
    service.tick()
    assert env.runtime.snapshot()["open_positions"] == 1
    service.configure(False)
    assert not service.staged.pending
    restarted = StagedPaperExecution(env.auto, env.repository, env.quotes)
    assert not restarted.pending
    assert env.runtime.snapshot()["open_positions"] == 1


def test_short_assumption_and_partial_pnl_are_visible(tmp_path, monkeypatch):
    blocked = environment(tmp_path, monkeypatch, IDS[1], borrow=False)
    assert not blocked.executor.pending
    assert blocked.runtime.trades.count() == 0
    env = environment(tmp_path, monkeypatch)
    position = fill(env)
    env.paper.monitor({"TCS": position.paper_plan["partial_target"]}, now=NOW)
    report = StrategyPaperReporting(env.paper).statement(now=NOW)
    row = next(row for row in report["rows"] if row["strategy_id"] == env.key)
    assert row["partial_exit_count"] == 1 and row["open_count"] == 1
    assert row["realized_pnl"] > 0 and row["unrealized_pnl"] > 0


@pytest.mark.parametrize("stop_during_scan", [False, True])
def test_trigger_worker_runs_during_scan_and_late_scan_cannot_undo_stop(
    tmp_path, monkeypatch, stop_during_scan
):
    env = environment(tmp_path, monkeypatch)
    scan_started, release_scan = threading.Event(), threading.Event()

    def scan(**kwargs):
        scan_started.set()
        assert release_scan.wait(timeout=4)
        return {**env.scan, "run_id": kwargs["run_id"]}

    service = StrategyPaperAutomation(
        scanner=SimpleNamespace(scan=scan),
        bridge=SimpleNamespace(
            paper_auto_entry=env.auto, SUPPORTED_MODES={"intraday", "swing"}
        ),
        repository=env.repository,
        quote_provider=env.quotes,
        paper_monitor=SimpleNamespace(tick=lambda **k: None),
        strategy_monitor=SimpleNamespace(tick=lambda **k: None),
        validation_getter=lambda: env.validation,
        validation_starter=lambda **k: None,
        clock=lambda: env.clock.now,
    )
    service.configure(True, strategy_ids=[env.key])
    if not stop_during_scan:
        service.staged.arm(
            env.scan, env.validation, [env.key], short_borrow_assumed=False, now=NOW
        )
        env.clock.price = 103.1

    async def check():
        assert await service.start()
        try:
            assert await asyncio.to_thread(scan_started.wait, 2)
            assert service._run_lock.locked()
            if stop_during_scan:
                service.configure(False)
            else:
                for _ in range(100):
                    if env.runtime.snapshot()["open_positions"] == 1:
                        break
                    await asyncio.sleep(0.01)
                assert env.runtime.snapshot()["open_positions"] == 1
                assert service._run_lock.locked()
                assert service._trigger_task is not None
                assert not service._trigger_task.done()
        finally:
            release_scan.set()
            assert await service.stop()
        assert service._task.done() and service._trigger_task.done()
        assert not service.staged.pending
        assert env.runtime.snapshot()["open_positions"] == (
            0 if stop_during_scan else 1
        )

    asyncio.run(check())


def test_overlapping_trigger_polls_do_not_duplicate_entries(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    env.clock.price = 103.1
    with env.executor._poll_lock:
        assert env.executor.process(
            now=NOW, validation=env.validation, admission_guard=lambda c: True
        ) == {"status": "busy", "opened_count": 0}
    assert env.runtime.snapshot()["open_positions"] == 0
    fill(env)
    assert env.runtime.trades.count() == 1


def test_three_shared_slots_and_overlapping_signals_cannot_duplicate_stock(
    tmp_path, monkeypatch
):
    from copy import deepcopy

    env = environment(tmp_path, monkeypatch)
    base = env.scan["top_picks"][0]
    env.executor.cancel()
    env.scan["top_picks"] = [
        {**deepcopy(base), "symbol": symbol} for symbol in ["A", "B", "C", "D", "A"]
    ]
    env.scan.update(requested_symbols=4, completed_symbols=4)
    env.executor.arm(
        env.scan, env.validation, [env.key], short_borrow_assumed=False, now=NOW
    )
    env.clock.price = 103.1
    result = env.executor.process(
        now=NOW, validation=env.validation, admission_guard=lambda c: True
    )
    assert result["opened_count"] == 3
    positions = env.runtime.snapshot()["positions"]
    assert len({row["symbol"] for row in positions}) == 3
    assert sum(row["quantity"] * row["average_price"] for row in positions) <= 80000
    assert (
        env.executor.process(
            now=NOW, validation=env.validation, admission_guard=lambda c: True
        )["opened_count"]
        == 0
    )


def test_daily_loss_gate_counts_exit_date_of_older_positions(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch, mode="swing")
    position = fill(env)
    env.runtime.trades.db.execute(
        "UPDATE trade_history SET created_at='2026-10-30T10:00:00+05:30'"
    )
    env.paper.monitor({"TCS": position.average_price - 25}, now=NOW)
    assert env.auto._daily_realized_loss("2026-11-02") > 3000
    assert env.auto._daily_realized_loss("2026-10-30") == 0


def test_real_nifty_scanner_feeds_persisted_next_candle_paper_trigger(
    tmp_path, monkeypatch
):
    from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner

    env = environment(tmp_path, monkeypatch)
    pair = signal_frame(env.key, mode="intraday")
    dates = pd.bdate_range("2026-10-15", "2026-10-30")
    index = [
        stamp
        for day in dates
        for stamp in pd.date_range(
            day.strftime("%Y-%m-%d") + " 09:15", periods=25, freq="15min", tz=TZ
        )
    ]
    index += list(pd.date_range("2026-11-02 09:15", periods=4, freq="15min", tz=TZ))
    frame = pd.concat(
        [pair.iloc[:1]] * (len(index) - 1) + [pair.iloc[-1:]], ignore_index=True
    )
    frame.index = pd.DatetimeIndex(index)
    monkeypatch.setenv(
        "TRENDFORGE_MULTI_STRATEGY_RESULTS_PATH", str(tmp_path / "scan.json")
    )
    scanner = MultiStrategyNiftyScanner(
        market_data=SimpleNamespace(
            batch_candles_with_errors=lambda *a, **k: ({"TCS": frame}, {})
        ),
        indicator_engine=SimpleNamespace(calculate=lambda f: f),
        universe_provider=SimpleNamespace(
            load=lambda *a, **k: {"members": [{"symbol": "TCS"}], "count": 1}
        ),
        state_repository=env.repository,
    )
    scan = scanner.scan(
        universe="NIFTY 500", mode="intraday", strategy_ids=[env.key], now=NOW
    )
    assert scan["completed_symbols"] == 1 and scan["error_symbols"] == 0
    env.executor.cancel()
    outcomes = env.executor.arm(
        scan, env.validation, [env.key], short_borrow_assumed=False, now=NOW
    )
    assert outcomes[0]["candidate_count"] == 1
    position = fill(env)
    assert position.strategy_id == env.key
    assert position.source_scan_run_id == scan["run_id"]


def test_disabled_quote_monitor_blocks_automation_entries():
    from tests.test_saved_strategy_automation import build

    env = build()
    env.service.paper_monitor.health = lambda: {"enabled": False, "running": False}
    env.service.configure(True)
    assert "paper_quote_monitor_not_running" in env.service.tick()["blockers"]
    assert not env.scans


def test_staged_entries_keep_the_configured_confidence_floor(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    env.auto.minimum_confidence = 95
    env.clock.price = 103.1
    result = env.executor.process(
        now=NOW, validation=env.validation, admission_guard=lambda c: True
    )
    assert result["opened_count"] == 0
    assert "confidence_below_minimum" in result["events"][0]["reasons"]
    assert env.runtime.snapshot()["open_positions"] == 0


def test_final_admission_rechecks_current_validation(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    from tests.test_saved_strategy_automation import build

    state = build(now=NOW)
    state.service.configure(True)
    candidate = {
        "strategy_id": env.key,
        "technical_mode": "intraday",
        "validation_run_id": "old-validation",
        "entry_bar_at": "2026-11-02T10:00:00+05:30",
        "automation_quote_at": NOW.isoformat(),
    }
    assert state.service._admit(state.service._generation, candidate) is False
