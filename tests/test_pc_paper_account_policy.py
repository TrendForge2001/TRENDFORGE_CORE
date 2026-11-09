"""Durable account caps for automated and supervised PC paper entries."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from core.database import initialize_database
from core.pc_paper_policy import POLICY_PATH, policy_environment
from database.database import Database
from database.repositories.trade_repository import TradeRepository
from services.paper_auto_entry_service import PaperAutoEntryService
from services.paper_trading_runtime import PaperTradingRuntime
from services.paper_trading_service import PaperTradingService
from tests.test_paper_auto_entry_service import candidate

NOW = datetime(2026, 11, 9, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def book(tmp_path, monkeypatch):
    for key, value in policy_environment().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("TRENDFORGE_PRODUCTION_RUNTIME", "false")
    monkeypatch.setenv("RENDER", "false")
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "false")
    path = str(tmp_path / "book.db")
    initialize_database(path)
    db = Database(path)
    repository = TradeRepository(db=db)
    runtime = PaperTradingRuntime(trades=repository)
    paper = PaperTradingService(runtime, enabled=True, environment_kill_switch=False)
    auto = PaperAutoEntryService(paper, enabled=True)
    yield SimpleNamespace(db=db, repository=repository, paper=paper, auto=auto)
    db.close()


def order(symbol, *, quantity=1, price=100, stop=90, target=120):
    return SimpleNamespace(
        symbol=symbol,
        side="BUY",
        quantity=quantity,
        price=price,
        stoploss=stop,
        target2=target,
    )


def test_pc_policy_uses_reviewed_defaults_and_rejects_execution_overrides(tmp_path):
    policy = json.loads(POLICY_PATH.read_text())
    env = policy_environment()
    assert env["TRENDFORGE_PAPER_MAX_DAILY_ENTRIES"] == "6"
    assert env["TRENDFORGE_PAPER_CASH_RESERVE_PERCENT"] == "0.0"
    assert env["TRENDFORGE_PAPER_MAX_OPEN_POSITIONS"] == "3"
    policy["TRENDFORGE_LIVE_TRADING_ENABLED"] = True
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    with pytest.raises(ValueError):
        policy_environment(path)


def test_six_entries_across_strategies_survive_service_restart(book):
    for index in range(6):
        request = order(f"S{index}")
        request.strategy_id = (
            "tf_intraday_ema9_20_momentum"
            if index % 2
            else "tf_intraday_vwma9_26_rsi_volume"
        )
        opened = book.paper.open(request, now=NOW)
        book.repository.close_trade(opened["trade_id"], 100, closed_at=NOW.isoformat())
        book.paper.runtime.portfolio.positions.clear()
        book.paper.runtime._trade_ids.clear()
    assert book.repository.entries_for_date(NOW.date().isoformat()) == 6
    restarted = PaperTradingService(
        PaperTradingRuntime(trades=book.repository),
        enabled=True,
        environment_kill_switch=False,
    )
    with pytest.raises(ValueError, match="account entry limit"):
        restarted.open(order("SEVENTH"), now=NOW)
    assert (
        "maximum_daily_entries_reached"
        in book.auto.evaluate_candidate(candidate(), now=NOW)["reasons"]
    )
    assert book.repository.count() == 6
    assert not book.auto.account_entry_limits(NOW + timedelta(days=1))["reasons"]


def test_partial_exit_is_not_a_second_entry_and_dates_use_ist(book):
    root = book.repository.save(
        "TCS", "BUY", 2, 100, created_at="2026-11-08T23:00:00+00:00"
    )
    child = book.repository.save(
        "TCS", "BUY", 1, 100, status="CLOSED", created_at=NOW.isoformat()
    )
    book.db.execute(
        "UPDATE trade_history SET parent_trade_id=? WHERE id=?", (root, child)
    )
    assert book.repository.entries_for_date("2026-11-09") == 1
    assert book.repository.entries_for_date("2026-11-08") == 0


def test_overlapping_entry_requests_cannot_exceed_daily_allowance(book):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    for index in range(5):
        key = book.repository.save(
            f"OLD{index}", "BUY", 1, 100, created_at=NOW.isoformat()
        )
        book.repository.close_trade(key, 100, closed_at=NOW.isoformat())
    barrier = Barrier(2)

    def enter(symbol):
        barrier.wait(timeout=5)
        try:
            book.paper.open(order(symbol), now=NOW)
            return "opened"
        except ValueError:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(enter, ["SIXTH", "SEVENTH"])) == ["blocked", "opened"]
    assert book.repository.entries_for_date("2026-11-09") == 6


def test_open_losses_and_realized_loss_combine_to_block_new_entries(book):
    loss = book.repository.save("CLOSED", "BUY", 10, 1000, created_at=NOW.isoformat())
    book.repository.close_trade(loss, 900, closed_at=NOW.isoformat())
    book.paper.open(order("OPEN", price=1000, stop=900, target=1200), now=NOW)
    book.paper.runtime.portfolio.positions["OPEN"].pnl = -2000
    limits = book.auto.account_entry_limits(NOW)
    assert limits["daily_realized_pnl"] == -1000
    assert limits["open_unrealized_pnl"] == -2000
    assert limits["daily_loss"] == limits["daily_loss_limit"] == 3000
    with pytest.raises(ValueError, match="account entry limit"):
        book.paper.open(order("BLOCKED"), now=NOW)


def test_position_cap_and_manual_risk_cannot_be_bypassed(book):
    with pytest.raises(ValueError, match="per-trade risk"):
        book.paper.open(order("LARGE", quantity=101), now=NOW)
    with pytest.raises(ValueError, match="protective"):
        book.paper.open(order("UNPROTECTED", stop=0), now=NOW)
    with pytest.raises(ValueError, match="reward/risk"):
        book.paper.open(order("WRONG_STOP", stop=110), now=NOW)
    with pytest.raises(ValueError, match="reward/risk"):
        book.paper.open(order("LOW_REWARD", target=105), now=NOW)
    for name in ("A", "B", "C"):
        book.paper.open(order(name), now=NOW)
    with pytest.raises(ValueError, match="account entry limit"):
        book.paper.open(order("FOURTH"), now=NOW)
    assert book.repository.count() == 3


def test_corrupt_entry_time_and_marks_fail_closed(book):
    opened = book.paper.open(order("TCS"), now=NOW)
    book.paper.runtime.portfolio.positions["TCS"].pnl = float("nan")
    assert "paper_equity_unavailable" in book.auto.account_entry_limits(NOW)["reasons"]
    book.paper.runtime.portfolio.positions["TCS"].pnl = 0
    book.db.execute(
        "UPDATE trade_history SET created_at='invalid' WHERE id=?",
        (opened["trade_id"],),
    )
    assert (
        "daily_entry_count_unavailable"
        in book.auto.account_entry_limits(NOW)["reasons"]
    )
