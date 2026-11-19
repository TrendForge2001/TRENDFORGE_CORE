"""Economic, timing and account parity for the corrected research pipeline."""

from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest.aligned_paper_book import run_shared_book
from backtest.approved_strategy_engine import ApprovedStrategyBacktestEngine
from core.database import initialize_database
from core.pc_paper_policy import policy_environment
from database.database import Database
from database.repositories.trade_repository import TradeRepository
from scanner import approved_strategies as rules
from scanner.strategy_registry import REGISTRY_VERSION
from services.aligned_signals import signals
from services.approved_admission import prepare
from services.paper_admission_policy import admit, capture, fingerprint, validate
from services.paper_auto_entry_service import PaperAutoEntryService
from services.paper_trading_runtime import PaperTradingRuntime
from services.paper_trading_service import PaperTradingService
from services.replay_store import ReplayStore
from services.research_history import cutoff, entry_sessions, fetch_days
from services.validation_journal import ValidationJournal
from tests.test_approved_horizon_strategies import pair

NOW = pd.Timestamp("2026-11-18 09:30", tz="Asia/Kolkata")


@pytest.fixture
def book(tmp_path, monkeypatch):
    for key, value in policy_environment().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "paper.db"))
    monkeypatch.setenv("TRENDFORGE_PRODUCTION_RUNTIME", "false")
    monkeypatch.setenv("RENDER", "false")
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "false")
    initialize_database()
    db = Database()
    repo = TradeRepository(db=db)
    runtime = PaperTradingRuntime(trades=repo)
    paper = PaperTradingService(runtime, enabled=True, environment_kill_switch=False)
    auto = PaperAutoEntryService(paper, enabled=True)
    yield SimpleNamespace(
        auto=auto, runtime=runtime, repo=repo, policy=capture(auto), path=tmp_path
    )
    db.close()


def flat_state():
    return dict(
        symbol_open=False,
        symbol_entered_today=False,
        open_positions=0,
        daily_entries=0,
        daily_realized_loss=0.0,
        daily_realized_pnl=0.0,
        unrealized_pnl=0.0,
        equity=100000.0,
        realized_pnl=0.0,
        committed=0.0,
        open_entry_fees=0.0,
    )


def test_capture_is_frozen_and_policy_changes_invalidate_the_fingerprint(book):
    frozen = deepcopy(book.policy)
    book.auto.minimum_rr = 3.5
    assert book.policy == frozen
    assert fingerprint(capture(book.auto)) != fingerprint(frozen)
    invalid = {**frozen, "capital": float("nan")}
    with pytest.raises(ValueError):
        validate(invalid)


def test_paper_candidate_and_historical_policy_have_identical_admission(book):
    key, context, _, source = pair(1)
    source.name = NOW - pd.Timedelta(minutes=15)
    plan = rules.plan_for(key, source, context)
    candidate = {
        "symbol": "SAMPLE",
        "strategy_id": key,
        "technical_mode": "intraday",
        "execution_eligible": True,
        "paper_plan": plan,
        "signal": {
            "signal": "BUY",
            "overall_score": 100,
            "confidence": 90,
            "entry": plan["entry"],
            "stoploss": plan["stoploss"],
            "target2": 0,
        },
    }
    paper = book.auto.evaluate_candidate(candidate, now=NOW.to_pydatetime())
    prepared = prepare(key, plan, plan["entry"], book.policy)
    historical = admit(
        book.policy,
        plan=prepared,
        score=100,
        confidence=90,
        now=NOW.to_pydatetime(),
        state=flat_state(),
    )
    assert paper["approved"] and historical["approved"]
    assert paper["quantity"] == historical["quantity"]
    assert paper["policy_hash"] == historical["policy_hash"]
    assert paper["entry"] == prepared["entry"]
    book.auto.minimum_confidence = 95
    paper = book.auto.evaluate_candidate(candidate, now=NOW.to_pydatetime())
    historical = admit(
        capture(book.auto),
        plan=prepared,
        score=100,
        confidence=90,
        now=NOW.to_pydatetime(),
        state=flat_state(),
    )
    assert paper["reasons"] == historical["reasons"] == ["confidence_below_minimum"]


def test_monthly_pnl_realizes_partial_fills_in_their_actual_month():
    from services.multi_strategy_validation_service import (
        MultiStrategyValidationService,
    )

    service = MultiStrategyValidationService(
        scanner_service=SimpleNamespace(
            market_data=None, indicators=None, strategies=None, universe_provider=None
        )
    )
    trade = {
        "symbol": "SAMPLE",
        "strategy_id": rules.IDS[4],
        "mode": "swing",
        "membership": {"NIFTY 500": True},
        "exit_at": "2026-02-02T09:15:00+05:30",
        "net_pnl": 30,
        "exit_legs": [
            {
                "exit_at": "2026-01-30T10:00:00+05:30",
                "gross_pnl": 55,
                "transaction_costs": 5,
                "net_pnl": 50,
            },
            {
                "exit_at": "2026-02-02T09:15:00+05:30",
                "gross_pnl": -15,
                "transaction_costs": 5,
                "net_pnl": -20,
            },
        ],
    }
    rows = service._monthly_pnl(universes=["NIFTY 500"], trades=[trade])
    assert [r["net_pnl"] for r in rows] == [50, -20]
    assert [r["exit_fills"] for r in rows] == [1, 1]
    assert [r["trades"] for r in rows] == [0, 1]
    assert sum(r["net_pnl"] for r in rows) == 30


def test_target_must_cover_fees_even_when_it_meets_two_r(book):
    plan = dict(
        entry=100.0,
        stoploss=99.99,
        target2=100.02,
        direction=1,
        mode="swing",
        annual=False,
    )
    result = admit(
        book.policy,
        plan=plan,
        score=100,
        confidence=90,
        now=NOW.to_pydatetime(),
        state=flat_state(),
    )
    assert "reward_risk_below_minimum" not in result["reasons"]
    assert result["reasons"] == ["target_does_not_cover_modeled_costs"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"daily_entries": 6}, "maximum_daily_entries_reached"),
        ({"symbol_entered_today": True}, "symbol_already_traded_today"),
        ({"open_positions": 3}, "maximum_open_positions_reached"),
        ({"unrealized_pnl": -3000, "equity": 97000}, "maximum_daily_loss_reached"),
    ],
)
def test_saved_account_guards_apply_to_historical_admission(book, change, reason):
    _, context, _, source = pair(1)
    plan = rules.plan_for(rules.IDS[0], source, context, entry=110.055)
    state = {**flat_state(), **change}
    result = admit(
        book.policy,
        plan=plan,
        score=100,
        confidence=90,
        now=NOW.to_pydatetime(),
        state=state,
    )
    assert not result["approved"] and reason in result["reasons"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True])
def test_nonfinite_or_corrupt_account_state_cannot_pass_admission(book, bad):
    _, context, _, source = pair(1)
    plan = rules.plan_for(rules.IDS[0], source, context, entry=110.055)
    with pytest.raises(ValueError):
        admit(
            book.policy,
            plan=plan,
            score=100,
            confidence=90,
            now=NOW.to_pydatetime(),
            state={**flat_state(), "committed": bad},
        )


def test_daily_entry_uses_observed_0930_and_ignores_earlier_high(book):
    key, context, previous, source = pair(12, "swing")
    source["FIB_WEEK_R1"], source["FIB_WEEK_R2"] = 140, 160
    entered = source.copy()
    entered.name = source.name + pd.Timedelta(days=1)
    entered["open"], entered["high"], entered["low"], entered["close"] = (
        110,
        141,
        109,
        112.3,
    )
    frame = pd.DataFrame([previous, source, entered])
    sessions = pd.DataFrame(
        [dict(open=112, high=113, low=111, close=112.3)],
        index=pd.DatetimeIndex([entered.name.normalize()]),
    )
    result = ApprovedStrategyBacktestEngine().run(
        {"SAMPLE": frame},
        strategy_id=key,
        mode="swing",
        interval="1d",
        admission_policy=book.policy,
        execution_sessions=sessions,
    )
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert pd.Timestamp(trade["entry_at"]).hour == 9
    assert pd.Timestamp(trade["entry_at"]).minute == 30
    assert trade["entry_raw_price"] == 112
    assert trade["entry_price"] == pytest.approx(112 * 1.0005)
    assert trade["exit_reason"] == "END_OF_TEST"
    assert trade["net_pnl"] == pytest.approx(result["metrics"]["net_profit"])
    missing = ApprovedStrategyBacktestEngine().run(
        {"SAMPLE": frame},
        strategy_id=key,
        mode="swing",
        interval="1d",
        admission_policy=book.policy,
        execution_sessions=sessions.iloc[:0],
    )
    assert not missing["trades"]
    assert (
        missing["rejection_counts"]["observed_0930_execution_session_unavailable"] == 1
    )
    from scanner.strategy_registry import get_strategy
    from services.multi_strategy_validation_service import (
        MultiStrategyValidationService,
    )

    service = MultiStrategyValidationService(
        scanner_service=SimpleNamespace(
            market_data=None, indicators=None, strategies=None, universe_provider=None
        )
    )
    rows = service._aggregate(
        universes=["NIFTY 500"],
        modes=["swing"],
        strategy_rows={"swing": [get_strategy(key)]},
        tested_symbols=["SAMPLE"],
        membership_sets={"NIFTY 500": {"SAMPLE"}},
        capital=100000,
        trades=[],
        backtests=[
            dict(
                symbol="SAMPLE",
                mode="swing",
                strategy_id=key,
                status="completed",
                membership={"NIFTY 500": True},
                **missing["metrics"],
            )
        ],
    )
    assert rows[0]["admission_rejection_samples"] == [
        dict(
            symbol="SAMPLE",
            decision_at=(
                entered.name.normalize() + pd.Timedelta(hours=9, minutes=30)
            ).isoformat(),
            reason="observed_0930_execution_session_unavailable",
        )
    ]


def test_execution_sessions_require_real_0930_and_complete_post_entry_bars():
    index = pd.date_range(
        "2026-11-18 09:15", "2026-11-18 15:15", freq="15min", tz="Asia/Kolkata"
    )
    frame = pd.DataFrame(
        dict(open=110.0, high=112.0, low=109.0, close=111.0), index=index
    )
    frame.loc[index[0], "high"] = 999
    session = entry_sessions(frame)
    assert session.iloc[0]["high"] == 112
    assert entry_sessions(frame.drop(index[1])).empty
    assert entry_sessions(frame.drop(index[9])).empty


def test_reference_seeds_precede_the_requested_window():
    end = pd.Timestamp("2026-11-18 15:30", tz="Asia/Kolkata")
    days = fetch_days(end, "5y", "1d")
    start = end.normalize() - pd.Timedelta(days=days)
    assert start < pd.Timestamp("2020-01-01", tz="Asia/Kolkata")
    assert cutoff(end, "5y") == pd.Timestamp("2021-11-18", tz="Asia/Kolkata")
    assert fetch_days(end, "60d", "15m") > 120


def make_store(book, symbols=("D", "C", "B", "A")):
    journal = ValidationJournal(
        "shared-fixture", {}, REGISTRY_VERSION, root=book.path / "replay"
    )
    store = ReplayStore(journal)
    _, _, previous, trigger = pair(1)
    index = pd.date_range(
        "2026-11-18 09:15", "2026-11-18 15:15", freq="15min", tz="Asia/Kolkata"
    )
    rows = []
    for i, stamp in enumerate(index):
        row = (previous if i == 0 else trigger).copy()
        row.name = stamp
        row["VWMA_9"] = 107 if i == 0 else 109
        row["VWMA_26"] = 108
        row["EMA_100"], row["EMA_200"] = 109, 108
        if i >= 2:
            row["open"], row["high"], row["low"], row["close"] = 110, 113, 109, 111
        if stamp.hour == 15 and stamp.minute == 0:
            row["open"], row["close"] = 112, 112
        rows.append(row)
    native = pd.DataFrame(rows)
    for symbol in symbols:
        store.save("native_intra", symbol, native)
        store.save("quotes", symbol, native[["open", "high", "low", "close"]])
        store.save_signals(
            "intraday", symbol, signals(native, "intraday"), index[0], native
        )
    return journal, store, native


def test_shared_book_is_one_cash_pool_with_three_positions_and_reconciles(book):
    journal, store, native = make_store(book)
    try:
        result = run_shared_book(
            store,
            symbols=["D", "C", "B", "A"],
            policy=book.policy,
            as_of=native.index[-1] + pd.Timedelta(minutes=15),
        )
        assert result["initial_capital"] == 100000
        assert result["max_observed_positions"] == 3
        assert result["minimum_cash"] >= 0
        assert result["net_pnl"] == pytest.approx(
            sum(t["net_pnl"] for t in result["trades"])
        )
        assert result["net_pnl"] == pytest.approx(
            result["gross_pnl_before_transaction_costs"] - result["transaction_costs"]
        )
        assert result["trades"][0]["symbol"] == "D"  # scanner's stable universe order
        assert all(
            point["capital_committed"] <= 100000 for point in result["equity_curve"]
        )
        assert result["research_only"] and result["paper_entries_changed"] is False
    finally:
        store.close()
        journal.close()


def test_shared_book_does_not_silently_drop_a_failed_universe_member(book):
    journal, store, native = make_store(book)
    try:
        store.path("quotes", "A").unlink()
        result = run_shared_book(
            store,
            symbols=["D", "C", "B", "A"],
            policy=book.policy,
            as_of=native.index[-1] + pd.Timedelta(minutes=15),
        )
        assert result["total_trades"] == 0
        assert result["rejection_counts"]["scan_not_fully_completed"] > 0
    finally:
        store.close()
        journal.close()


def test_paper_costed_partial_and_final_exits_charge_delivery_only_once(book):
    key, context, _, source = pair(5, "swing")
    source["FIB_YEAR_R1"], source["FIB_YEAR_R2"], source["FIB_YEAR_R3"] = 140, 160, 180
    raw_plan = rules.plan_for(key, source, context)
    plan = prepare(key, raw_plan, 110, book.policy)
    quantity = 4
    order = SimpleNamespace(
        symbol="SAMPLE",
        side="BUY",
        quantity=quantity,
        price=plan["entry"],
        stoploss=plan["stoploss"],
        target2=plan["target2"],
        trade_mode="swing",
        strategy_id=key,
        paper_plan=plan,
    )
    entry = NOW.to_pydatetime()
    book.runtime.open(order, now=entry)
    assert book.runtime.snapshot()["unrealized_pnl"] < 0
    closed = book.runtime.monitor(
        {"SAMPLE": 180.0}, now=(NOW + pd.Timedelta(days=1)).to_pydatetime()
    )
    rows = [dict(r) for r in book.repo.closed_trades()]
    assert len(rows) == len(closed) == 2
    assert sum(r["delivery_charge"] for r in rows) == pytest.approx(15.34)
    assert all(
        r["pnl"] == pytest.approx(r["gross_pnl"] - r["transaction_costs"]) for r in rows
    )
    assert book.runtime.snapshot()["realized_pnl"] == pytest.approx(
        sum(r["pnl"] for r in rows)
    )
    assert not book.runtime.snapshot()["positions"]


def test_corrected_validation_runs_real_pipeline_and_shared_book(book):
    from indicators.indicator_engine import IndicatorEngine
    from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner
    from services.multi_strategy_validation_service import (
        MultiStrategyValidationService,
    )

    as_of = pd.Timestamp.now(tz="Asia/Kolkata").normalize() - pd.Timedelta(days=1)
    while as_of.weekday() >= 5:
        as_of -= pd.Timedelta(days=1)
    as_of += pd.Timedelta(hours=15, minutes=30)
    daily_index = pd.date_range(
        as_of.normalize() - pd.DateOffset(years=7), as_of.normalize(), freq="B"
    )
    native_index = pd.DatetimeIndex(
        [
            day + pd.Timedelta(hours=9, minutes=15 + 15 * offset)
            for day in daily_index[-85:]
            for offset in range(25)
        ]
    )
    daily = pd.DataFrame(
        dict(open=100.0, high=101.0, low=99.0, close=100.0, volume=1000),
        index=daily_index,
    )
    native = pd.DataFrame(
        dict(open=100.0, high=101.0, low=99.0, close=100.0, volume=1000),
        index=native_index,
    )
    calls = []

    def fetch(symbols, *, period, interval):
        calls.append((list(symbols), period, interval))
        return {s: (daily if interval == "1d" else native).copy() for s in symbols}, {}

    scanner = MultiStrategyNiftyScanner(
        market_data=SimpleNamespace(batch_candles_with_errors=fetch),
        indicator_engine=IndicatorEngine(),
        universe_provider=SimpleNamespace(
            load=lambda *a, **kw: {"members": [{"symbol": "SAMPLE"}]}
        ),
    )
    request = dict(
        capital=100000, admission_policy=book.policy, evaluation_as_of=as_of.isoformat()
    )
    journal = ValidationJournal(
        "integration", request, REGISTRY_VERSION, root=book.path / "journal"
    )
    try:
        result = MultiStrategyValidationService(scanner_service=scanner).run(
            **request,
            modes=["intraday", "swing", "positional"],
            universes=["NIFTY 500"],
            shared_book=True,
            checkpoint=journal,
        )
        assert not list(result["errors"]), "\n".join(
            row["error"] for row in result["errors"]
        )
        assert len(result["backtest_results"]) == 23
        assert result["admission_policy_hash"] == fingerprint(book.policy)
        assert result["shared_book"]["requested_symbols"] == 1
        assert result["shared_book"]["complete_quote_bars"] > 0
        assert len(journal.completed()) == 3
        for row in result["strategy_universe_metrics"]:
            assert row["loss_making_symbols"] == 0
            assert row["no_trade_symbols"] == 1
            assert row["flat_traded_symbols"] == 0
            assert row["admission_policy_hash"] == fingerprint(book.policy)
        assert all(symbols for symbols, _, _ in calls)
        assert (
            sum(
                interval == "1d" and int(period[:-1]) > 2000
                for _, period, interval in calls
                if period.endswith("d")
            )
            == 1
        )
    finally:
        journal.close()


def test_broker_seed_fetches_stay_inside_range_limits():
    from datetime import timedelta

    from providers.kite_provider import KiteProvider

    provider = object.__new__(KiteProvider)
    calls = []
    provider._pace_history = lambda: None
    provider.safe_historical = lambda token, start, end, interval, **kwargs: (
        calls.append((start, end, interval)) or []
    )
    start = NOW.to_pydatetime()
    for interval, days, limit in [("day", 2600, 1800), ("15minute", 1830, 120)]:
        calls.clear()
        provider._historical_rows(1, start, start + timedelta(days=days), interval)
        assert calls[0][0] == start
        assert calls[-1][1] == start + timedelta(days=days)
        assert all(end - begin <= timedelta(days=limit) for begin, end, _ in calls)
        assert all(calls[i][1] == calls[i + 1][0] for i in range(len(calls) - 1))


def test_corrected_operator_freezes_policy_and_never_starts_paper(book, monkeypatch):
    import asyncio
    import json
    from datetime import UTC, datetime, timedelta

    from database.repositories.strategy_runtime_state_repository import (
        StrategyRuntimeStateRepository,
    )
    from services.paper_operator_request import BASE_CHECKS, run_paper_operator_request

    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TRENDFORGE_CLOUD_PAPER_EXECUTION", "true")
    repository = StrategyRuntimeStateRepository(db_path=str(book.path / "paper.db"))
    now = datetime.now(UTC)
    requests, starts = [], []
    status = dict(
        universe="NIFTY 500",
        target_symbols=None,
        target_strategy_ids=None,
        assume_short_borrow=False,
        control_generation=0,
        enabled=False,
        paper_only=True,
        broker_orders_allowed=False,
        account_policy={"capital": 100000},
    )
    automation = SimpleNamespace(
        repository=repository,
        CONFIG_KEY="paper.automation.config.v1",
        status=lambda: status,
        bridge=SimpleNamespace(paper_auto_entry=book.auto),
        configure=lambda *args, **kwargs: starts.append(args),
    )
    request = dict(
        id="c" * 32,
        action="run_corrected_research",
        registry_version=REGISTRY_VERSION,
        authorized_at=(now - timedelta(seconds=1)).isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(),
        confirm_render_executor=True,
    )

    def start(payload):
        requests.append(payload)
        return {"status": "running"}

    try:
        asyncio.run(
            run_paper_operator_request(
                json.dumps(request),
                automation_getter=lambda: automation,
                validation_getter=lambda: {},
                validation_starter=start,
                readiness=lambda: {"checks": dict.fromkeys(BASE_CHECKS, True)},
                clock=lambda: now,
            )
        )
        assert len(requests) == 1
        assert requests[0]["admission_policy"] == book.policy
        assert requests[0]["shared_book"] is True
        assert requests[0]["assume_short_borrow"] is False
        assert not starts and status["enabled"] is False
        assert pd.Timestamp(requests[0]["evaluation_as_of"]) < pd.Timestamp(now)
        assert (
            repository.load_state("paper.operator:" + request["id"])["payload"]["phase"]
            == "corrected_research_requested"
        )
    finally:
        repository.close()
