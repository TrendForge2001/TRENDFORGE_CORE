"""Real persistence, interruption/resume equivalence and bounded trade evidence."""

import json
import sqlite3
import threading
import tracemalloc
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from core.database import initialize_database
from scanner.strategy_registry import REGISTRY_VERSION
from services.multi_strategy_validation_runtime import _persist_validation, status
from services.multi_strategy_validation_service import MultiStrategyValidationService
from services.validation_journal import ValidationJournal, compact_trade, write_result


def journal(tmp_path, run="test-run", request=None):
    return ValidationJournal(run, request or {}, REGISTRY_VERSION, root=tmp_path)


def test_error_review_is_read_only_and_never_publishes_error_text(
    tmp_path, monkeypatch
):
    from services.validation_review import error_diagnostics

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "state.db"))
    saved = ValidationJournal("review-run", {}, REGISTRY_VERSION)
    for mode, message in [
        (
            "intraday",
            "ValueError: Intraday history is missing its 15:00 IST square-off candle",
        ),
        ("intraday", "Kite private-account-secret"),
        ("swing", "KeyError: private-field-secret"),
    ]:
        saved.rows["errors"].append(dict(mode=mode, phase="backtest", error=message))
    saved.commit_unit("intraday", "PRIVATE")
    snapshot = dict(run_id="review-run", request={})
    result = error_diagnostics(snapshot)
    assert result["status"] == "available" and result["total_errors"] == 3
    assert {row["cause"] for row in result["counts"]} == {
        "missing_1500_square_off_candle",
        "unclassified",
        "missing_indicator_or_field",
    }
    assert "private" not in json.dumps(result).lower()
    assert len(saved.rows["errors"]) == 3 and saved.completed() == {
        ("intraday", "PRIVATE")
    }
    assert (
        error_diagnostics({**snapshot, "request": {"changed": True}})["status"]
        == "unavailable"
    )
    assert (
        error_diagnostics({"run_id": "missing", "request": {}})["status"]
        == "unavailable"
    )
    saved.close()


def test_atomic_units_survive_reopen_without_duplicates_or_lost_fills(tmp_path):
    first = journal(tmp_path)
    first.bind_universe(["A", "B"], {"NIFTY 100": {"A", "B"}})
    first.rows["backtests"].append({"symbol": "A", "net_profit": 8.0})
    first.rows["trades"].append(
        {"symbol": "A", "gross_pnl": 10.0, "transaction_costs": 2.0, "net_pnl": 8.0}
    )
    first.commit_unit("intraday", "A")
    assert first.rows["trades"].pending == []
    first.close()
    restored = journal(tmp_path)
    assert restored.completed() == {("intraday", "A")}
    assert list(restored.rows["trades"])[0]["net_pnl"] == 8.0
    restored.rows["trades"].append({"symbol": "B", "net_pnl": -3.0})
    restored.commit_unit("intraday", "B")
    assert sum(row["net_pnl"] for row in restored.rows["trades"]) == 5.0
    assert len(restored.rows["trades"]) == 2
    with pytest.raises(sqlite3.IntegrityError):
        restored.commit_unit("intraday", "A")
    assert len(restored.rows["trades"]) == 2
    restored.close()


def test_checkpoint_rejects_changed_rules_request_and_universe(tmp_path):
    original = journal(tmp_path, request={"capital": 100000})
    original.bind_universe(["A"], {"NIFTY 100": {"A"}})
    original.close()
    with pytest.raises(ValueError, match="unused run ID"):
        ValidationJournal(
            "test-run", {"capital": 100000}, REGISTRY_VERSION, root=tmp_path, fresh=True
        )
    with pytest.raises(ValueError, match="does not match"):
        ValidationJournal(
            "test-run", {"capital": 200000}, REGISTRY_VERSION, root=tmp_path
        )
    with pytest.raises(ValueError, match="does not match"):
        ValidationJournal("test-run", {"capital": 100000}, "older-rules", root=tmp_path)
    restored = journal(tmp_path, request={"capital": 100000})
    with pytest.raises(ValueError, match="membership changed"):
        restored.bind_universe(["B"], {"NIFTY 100": {"B"}})
    restored.close()


def test_retry_failed_units_preserves_successful_ledger_and_cutoff(tmp_path):
    saved = journal(tmp_path)
    cutoff = saved.metadata["as_of"]
    saved.rows["trades"].append({"symbol": "GOOD", "net_pnl": 12})
    saved.commit_unit("swing", "GOOD")
    saved.rows["errors"].append({"symbol": "BAD", "error": "failure"})
    saved.commit_unit("intraday", "BAD")
    assert saved.retry_failed() == 1
    saved.close()
    restored = journal(tmp_path)
    assert restored.completed() == {("swing", "GOOD")}
    assert list(restored.rows["trades"]) == [{"symbol": "GOOD", "net_pnl": 12}]
    assert restored.metadata["as_of"] == cutoff and len(restored.rows["errors"]) == 0
    restored.rows["errors"].append({"error": "pending"})
    with pytest.raises(ValueError, match="before processing"):
        restored.retry_failed()
    restored.close()


@pytest.mark.parametrize("recover_pending", [False, True])
def test_runtime_retry_reuses_completed_run_and_keeps_successful_stock(
    tmp_path, monkeypatch, recover_pending
):
    from services import multi_strategy_validation_runtime as runtime

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "state.db"))
    initialize_database()
    request = dict(universes=["NIFTY 100"], modes=["intraday"])
    saved = ValidationJournal("retry-run", request, REGISTRY_VERSION)
    cutoff = saved.metadata["as_of"]
    saved.rows["backtests"].append(dict(symbol="GOOD", net_profit=12))
    saved.commit_unit("intraday", "GOOD")
    saved.rows["errors"].append(dict(symbol="BAD", error="failure"))
    saved.commit_unit("intraday", "BAD")
    saved.close()
    app = FastAPI()
    app.state.r7253_validation = dict(
        status="interrupted" if recover_pending else "completed",
        run_id="retry-run",
        request=request,
        registry_version=REGISTRY_VERSION,
        checkpointed=True,
        as_of=cutoff,
        retry_failed_pending=recover_pending,
    )
    calls = []

    class Service:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            calls.append(kwargs)
            store = kwargs["checkpoint"]
            assert store.completed() == {("intraday", "GOOD")}
            assert store.metadata["as_of"] == cutoff
            store.rows["backtests"].append(dict(symbol="BAD", net_profit=3))
            store.commit_unit("intraday", "BAD")
            return dict(
                registry_version=REGISTRY_VERSION,
                as_of=cutoff,
                backtests=store.rows["backtests"],
                errors=store.rows["errors"],
            )

    monkeypatch.setattr(runtime, "MultiStrategyValidationService", Service)
    runtime._start_validation_locked(
        app,
        scanner_service=object(),
        request=request if recover_pending else {**request, "retry_failed": True},
    )
    app.state.r7253_validation["_thread"].join(timeout=5)
    assert len(calls) == 1 and "retry_failed" not in calls[0]
    assert app.state.r7253_validation["status"] == "completed"
    assert app.state.r7253_validation["run_id"] == "retry-run"
    assert app.state.r7253_validation["requeued_failed_units"] == 1
    result = json.loads(runtime.output_path().read_text())
    assert sum(row["net_profit"] for row in result["backtests"]) == 15


def test_retry_rejects_force_or_changed_scope_without_deleting_saved_work(
    tmp_path, monkeypatch
):
    from services import multi_strategy_validation_runtime as runtime

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "state.db"))
    initialize_database()
    app = FastAPI()
    app.state.r7253_validation = dict(
        status="completed",
        run_id="run",
        request={},
        checkpointed=True,
        as_of=datetime.now(UTC).isoformat(),
        registry_version=REGISTRY_VERSION,
    )
    for request in (
        {"retry_failed": True, "force": True},
        {"retry_failed": True, "modes": ["swing"]},
    ):
        with pytest.raises(ValueError, match="same completed recent"):
            runtime._start_validation_locked(
                app, scanner_service=object(), request=request
            )
        assert app.state.r7253_validation["status"] == "completed"


def test_compaction_keeps_economics_partial_fills_and_selected_indicators():
    trade = dict(
        symbol="A",
        quantity=3,
        entry_price=100.0,
        exit_price=110.0,
        gross_pnl=30.0,
        transaction_costs=2.0,
        net_pnl=28.0,
        signal_evidence={"oversized": [0] * 100000},
        entry_pivots={"huge": [0] * 10000},
        indicators={"EMA_9": 99.0, "SWING_HIGHS_20": [0] * 100000},
        technical_evidence={"cross": True},
        exit_legs=[
            dict(
                quantity=1,
                exit_price=105.0,
                gross_pnl=5.0,
                net_pnl=4.0,
                transaction_costs=1.0,
            ),
            dict(
                quantity=2,
                exit_price=112.5,
                gross_pnl=25.0,
                net_pnl=24.0,
                transaction_costs=1.0,
            ),
        ],
    )
    output = compact_trade(trade, ["EMA_9"])
    assert output["net_pnl"] == sum(row["net_pnl"] for row in output["exit_legs"])
    assert output["gross_pnl"] - output["transaction_costs"] == output["net_pnl"]
    assert output["indicators"] == {"EMA_9": 99.0}
    assert "signal_evidence" not in output and "entry_pivots" not in output
    assert len(json.dumps(output)) < 1500


def test_streamed_export_has_all_rows_without_materializing_or_stringifying_arrays(
    tmp_path, monkeypatch
):
    store = journal(tmp_path)
    tracemalloc.start()
    for unit in range(50):
        for trade in range(400):
            store.rows["trades"].append(
                dict(unit=unit, trade=trade, net_pnl=trade - 10)
            )
        store.commit_unit("swing", str(unit))
    assert store.rows["trades"].pending == []
    target = tmp_path / "result.json"
    write_result(target, {"status": "completed", "trades": store.rows["trades"]})
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 4 * 1024 * 1024
    report = json.loads(target.read_text())
    assert len(report["trades"]) == 20000
    assert (
        sum(row["net_pnl"] for row in report["trades"])
        == sum(t - 10 for t in range(400)) * 50
    )
    assert target.stat().st_mode & 0o077 == 0
    assert not target.with_name("result.json.partial").exists()
    store.close()


def test_persisted_running_job_is_interrupted_not_old_completed_or_performance_ready(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "state.db"))
    initialize_database()
    _persist_validation(
        dict(
            status="running",
            run_id="current",
            registry_version=REGISTRY_VERSION,
            checkpointed=True,
            request={"modes": ["intraday"]},
            progress={
                "processed_symbol_modes": 7,
                "total_symbol_modes": 10,
                "progress_pct": 70.0,
            },
        )
    )
    value = status(FastAPI())
    assert value["status"] == "interrupted"
    assert value["registry_current"] is True
    assert value["performance_results_ready"] is False
    assert value["restart_safe"] is True
    assert value["progress"]["processed_symbol_modes"] == 7
    assert value["worker_alive"] is False


def test_explicit_live_thread_status_remains_running():
    app = FastAPI()
    app.state.r7253_validation = dict(
        status="running", run_id="thread", _thread=threading.Thread()
    )
    assert status(app)["status"] == "running"


class Interrupted(BaseException):
    pass


def service_fixture():
    from indicators.indicator_engine import IndicatorEngine
    from scanner.multi_strategy_engine import MultiStrategyEngine
    from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner
    from services.yearly_reference import YearlyReferenceCache
    from tests.support.research_candles import SyntheticMarket

    data = SyntheticMarket()
    calls = []

    def fetch(symbols, **kw):
        calls.append(list(symbols))
        return data.batch_candles_with_errors(symbols, **kw)

    scanner = SimpleNamespace(
        market_data=SimpleNamespace(batch_candles_with_errors=fetch),
        strategies=MultiStrategyEngine(),
        indicators=IndicatorEngine(),
        yearly_references=YearlyReferenceCache(),
        universe_provider=SimpleNamespace(
            load=lambda *a, **k: {"members": [{"symbol": "A"}, {"symbol": "B"}]}
        ),
        _mode_config=MultiStrategyNiftyScanner._mode_config,
        _completed_bars=MultiStrategyNiftyScanner._completed_bars,
        _intraday_session_overrides=MultiStrategyNiftyScanner._intraday_session_overrides,
        _label=MultiStrategyNiftyScanner._label,
    )
    return MultiStrategyValidationService(scanner_service=scanner), calls


def test_interrupted_service_resumes_missing_stock_and_matches_uninterrupted_accounting(
    tmp_path,
):
    key = "tf_intraday_ema9_20_momentum"
    request = dict(
        universes=["NIFTY 100"], modes=["intraday"], strategy_ids=[key], chunk_size=1
    )
    first, calls = service_fixture()
    checkpoint = journal(tmp_path, request=request)

    def interrupt(update):
        if (
            update.get("processed_symbol_modes") == 1
            and update.get("phase") == "backtest"
        ):
            raise Interrupted()

    with pytest.raises(Interrupted):
        first.run(
            **request,
            run_id="test-run",
            checkpoint=checkpoint,
            progress_callback=interrupt,
        )
    assert checkpoint.completed() == {("intraday", "A")}
    checkpoint.close()
    resumed, calls = service_fixture()
    restored = journal(tmp_path, request=request)
    result = resumed.run(**request, run_id="test-run", checkpoint=restored)
    assert calls and all(chunk == ["B"] for chunk in calls)
    assert restored.completed() == {("intraday", "A"), ("intraday", "B")}
    reference, _ = service_fixture()
    fresh = journal(tmp_path, run="uninterrupted", request=request)
    # Identical cutoff and seed window, including the resume path.
    fresh.metadata["as_of"] = restored.metadata["as_of"]
    fresh._save_meta()
    expected = reference.run(**request, run_id="uninterrupted", checkpoint=fresh)
    assert result["strategy_universe_metrics"] == expected["strategy_universe_metrics"]
    assert result["monthly_pnl"] == expected["monthly_pnl"]
    assert list(result["trades"]) == list(expected["trades"])
    assert {t["symbol"] for t in result["trades"]} == {"A", "B"}
    assert not resumed.scanner.yearly_references._levels
    restored.close()
    fresh.close()


@pytest.mark.parametrize(
    "strategy_id",
    [
        "tf_intraday_ema9_20_momentum",
        "tf_intraday_vwma9_26_rsi_volume",
        "tf_intraday_ema_adx_continuation_short",
    ],
)
def test_fast_entry_prefilter_matches_full_public_evaluator(strategy_id):
    from backtest.approved_strategy_engine import ApprovedStrategyBacktestEngine
    from indicators.approved_strategies import add_native
    from indicators.indicator_engine import IndicatorEngine
    from scanner import approved_strategies as rules
    from tests.support.research_candles import SyntheticMarket

    class Reference(ApprovedStrategyBacktestEngine):
        def entry_evaluation(self, previous, row, context, strategy_id):
            return rules.evaluate(previous, row, context, strategy_id)

    raw, _ = SyntheticMarket().batch_candles_with_errors(["A"], interval="15m")
    frame = add_native(IndicatorEngine().calculate(raw["A"]))
    settings = dict(
        strategy_id=strategy_id,
        mode="intraday",
        interval="15m",
        short_borrow_available=True,
    )
    expected = Reference().run({"A": frame}, **settings)
    actual = ApprovedStrategyBacktestEngine().run({"A": frame}, **settings)
    assert actual == expected
    assert actual["trades"]


@pytest.mark.parametrize("authenticated", [True, False])
def test_startup_recovers_only_saved_validation_after_session_probe(
    tmp_path, monkeypatch, authenticated
):
    import asyncio

    from services import multi_strategy_validation_runtime as runtime

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "state.db"))
    initialize_database()
    request = {"modes": ["intraday"], "universes": ["NIFTY 100"]}
    _persist_validation(
        dict(
            status="running",
            run_id="resume",
            registry_version=REGISTRY_VERSION,
            checkpointed=True,
            as_of=datetime.now(UTC).isoformat(),
            request=request,
            progress={"processed_symbol_modes": 1, "total_symbol_modes": 2},
        )
    )
    calls = []
    monkeypatch.setattr(
        runtime,
        "start_validation",
        lambda app, **kwargs: calls.append(kwargs) or {"status": "running"},
    )
    app = FastAPI()

    async def check():
        async def probe():
            app.state.kite_session_probe = {"authenticated": authenticated}

        task = runtime.start_validation_recovery(
            app,
            scanner_getter=lambda: "scanner",
            session_probe=asyncio.create_task(probe()),
        )
        assert task is not None
        await task

    asyncio.run(check())
    assert len(calls) == int(authenticated)
    if authenticated:
        assert calls[0]["request"] == request
        assert calls[0]["scanner_service"] == "scanner"


def test_process_kill_preserves_committed_units_only(tmp_path):
    import subprocess
    import sys

    script = """
import os,sys
from services.validation_journal import ValidationJournal
journal=ValidationJournal('killed',{},sys.argv[2],root=sys.argv[1])
journal.rows['trades'].append({'symbol':'A','net_pnl':7})
journal.commit_unit('intraday','A')
journal.rows['trades'].append({'symbol':'B','net_pnl':99})
os._exit(137)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), REGISTRY_VERSION],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 137, result.stderr.decode()
    restored = journal(tmp_path, run="killed")
    assert restored.completed() == {("intraday", "A")}
    assert list(restored.rows["trades"]) == [{"symbol": "A", "net_pnl": 7}]
    restored.close()


def test_newer_manual_request_supersedes_automatic_recovery(monkeypatch):
    from services import multi_strategy_validation_runtime as runtime

    app = FastAPI()
    app.state.r7253_validation = dict(
        status="completed",
        run_id="newer",
        registry_version=REGISTRY_VERSION,
        request={},
    )

    def forbidden(*a, **k):
        raise AssertionError("Recovery must not replace a newer manual request")

    monkeypatch.setattr(runtime, "_start_validation_locked", forbidden)
    result = runtime.start_validation(
        app, scanner_service=object(), request={}, expected_run_id="older"
    )
    assert result["run_id"] == "newer" and result["status"] == "completed"


def test_final_aggregation_streams_wide_trade_evidence_with_bounded_memory(tmp_path):
    service, _ = service_fixture()
    store = journal(tmp_path, run="aggregation")
    key = "tf_intraday_ema9_20_momentum"
    symbols = [f"S{i}" for i in range(30)]
    sample = dict(
        side="LONG",
        quantity=10,
        entry_price=100.0,
        exit_price=101.0,
        entry_at="2026-11-02T10:00:00+05:30",
        exit_at="2026-11-02T11:00:00+05:30",
        gross_pnl=1.2,
        transaction_costs=0.2,
        net_pnl=1.0,
        stoploss=99.0,
        target=103.0,
        initial_stoploss=99.0,
        indicators={f"I{i}": float(i) for i in range(20)},
        technical_evidence={f"C{i}": True for i in range(8)},
        exit_legs=[
            dict(
                quantity=10,
                entry_price=100.0,
                exit_price=101.0,
                gross_pnl=1.2,
                transaction_costs=0.2,
                net_pnl=1.0,
                exit_reason="END_OF_TEST",
            )
        ],
    )
    for symbol in symbols:
        store.rows["backtests"].append(
            dict(
                symbol=symbol,
                mode="intraday",
                strategy_id=key,
                membership={"NIFTY 100": True},
                status="completed",
                net_profit=500.0,
                final_capital=100500.0,
                return_pct=0.5,
                max_drawdown_pct=1.0,
                transaction_costs=100.0,
            )
        )
        for i in range(500):
            store.rows["trades"].append(
                {
                    **sample,
                    "symbol": symbol,
                    "mode": "intraday",
                    "strategy_id": key,
                    "membership": {"NIFTY 100": True},
                    "trade_number": i,
                }
            )
        store.commit_unit("intraday", symbol)
    tracemalloc.start()
    result = service._aggregate(
        universes=["NIFTY 100"],
        modes=["intraday"],
        strategy_rows={
            "intraday": [
                {
                    "strategy_id": key,
                    "name": "fixture",
                    "source": "user_notebook",
                    "paper_eligible": True,
                }
            ]
        },
        tested_symbols=symbols,
        membership_sets={"NIFTY 100": set(symbols)},
        backtests=store.rows["backtests"],
        trades=store.rows["trades"],
        capital=100000.0,
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 8 * 1024 * 1024
    assert result[0]["total_trades"] == 15000
    assert result[0]["symbols_with_trades"] == 30
    assert result[0]["net_pnl"] == 15000.0
    assert result[0]["trade_wins"] == 15000
    assert result[0]["transaction_costs"] == 3000.0
    store.close()
