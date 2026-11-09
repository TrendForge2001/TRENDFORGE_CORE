"""Bounded Render research, read-only previews and explicit paper-host admission."""

import os
import threading
from concurrent.futures import Future
from contextlib import ExitStack
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from streamlit.testing.v1 import AppTest

from providers.kite_ticker import _timestamp
from scanner.portfolio_policy import evidence_rows
from services.kite_market_preflight import preview_order, scanner_input_checks
from services.research_archive import validate_batch
from services.research_batches import ResearchBatchManager
from services.research_capacity import ResearchCapacityExceeded, research_partitions
from services.research_report import build_report
from tests.test_research_batches import finish, request

pytest_plugins = ["tests.test_cloud_paper_storage", "tests.test_research_batches"]

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 9, 11, 0, tzinfo=TZ)


def test_streaming_epoch_retains_market_instant_without_host_timezone():
    epoch = NOW.timestamp()
    assert _timestamp(epoch) == NOW
    assert _timestamp(epoch).isoformat() == "2026-11-09T11:00:00+05:30"


@pytest.mark.parametrize("period", ["30d", "60d", "2y", "5y"])
def test_render_partitions_cover_every_symbol_once_per_strategy(monkeypatch, period):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "false")
    symbols = ["STOCK" + str(i) for i in range(500)]
    settings = [{"strategy_id": name, "period": period} for name in ("A", "B")]
    parts = research_partitions(symbols, settings[0], settings)
    from services.research_capacity import ESTIMATED_BARS

    for strategy in settings:
        selected = [p for p in parts if p["settings"] == strategy]
        assert [s for part in selected for s in part["symbols"]] == symbols
        assert all(len(p["symbols"]) <= 50 for p in selected)
        assert all(
            len(p["symbols"]) * ESTIMATED_BARS[period] <= 50000 for p in selected
        )


def test_campaign_runs_serially_and_archives_index_without_combining_pnl(
    technical, monkeypatch
):
    monkeypatch.setenv("RENDER", "false")
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "false")
    monkeypatch.setattr(
        "services.research_batches.research_partitions",
        lambda symbols, settings, strategies: [
            {"symbols": [symbol], "settings": settings} for symbol in symbols
        ],
    )
    manager = ResearchBatchManager(technical, import_history=False, isolated=False)
    try:
        batch = finish(manager, manager.submit("backtest", request()))
        assert batch["status"] == "completed"
        report = batch["report"]
        assert report["partition_count"] == 2
        assert "metrics" not in report
        assert report["report_type"] == "research_partition_manifest"
        children = [manager.repository.get(row["batch_id"]) for row in report["rows"]]
        assert children[0]["finished_at"] <= children[1]["started_at"]
        assert [child["request"]["symbols"] for child in children] == [
            ["TCS"],
            ["SBIN"],
        ]
        validate_batch(batch)
        broken = {**batch, "report": {**report, "partition_count": 3}}
        with pytest.raises(ValueError, match="manifest"):
            validate_batch(broken)
    finally:
        manager.close(wait=True)


def test_observed_row_limit_fails_entire_backtest_without_saving_results(technical):
    from services.portfolio_backtest_service import PortfolioBacktestService

    with pytest.raises(ResearchCapacityExceeded):
        PortfolioBacktestService(technical).run(
            symbols=["TCS", "SBIN"],
            mode="swing",
            strategy_id=request()["strategy_id"],
            max_candle_rows=1,
        )
    assert not technical.repository.latest()


class Broker:
    def health(self):
        return {"authenticated": True}

    def instruments(self, exchange):
        assert exchange == "NSE"
        return [
            {
                "exchange": "NSE",
                "segment": "NSE",
                "instrument_type": "EQ",
                "tradingsymbol": "TCS",
                "tick_size": 0.05,
                "lot_size": 1,
            }
        ]

    def quote(self, symbols):
        return {
            symbol: {"last_price": 100, "timestamp": NOW.isoformat()}
            for symbol in symbols
        }

    def place_order(self, **kwargs):
        pytest.fail("No broker writes are permitted")


def test_order_preview_uses_fresh_quote_validates_tick_and_cannot_submit():
    args = dict(
        symbol="TCS",
        side="BUY",
        product="MIS",
        quantity=2,
        stoploss=95,
        target=110,
        now=NOW,
    )
    result = preview_order(Broker(), **args)
    assert result["gross_stop_risk"] == 10 and result["gross_notional"] == 200
    assert result["reward_risk"] == 2
    assert result["orders_submitted"] == 0 and result["broker_orders_allowed"] is False
    assert result["expires_at"] == (NOW + timedelta(seconds=30)).isoformat()
    for invalid in (
        {"side": "SHORT", "product": "CNC"},
        {"stoploss": 95.01},
        {"quantity": True},
        {"symbol": "DUMMYHEG"},
        {"now": NOW + timedelta(minutes=2)},
        {"stoploss": 105},
        {"target": float("nan")},
    ):
        with pytest.raises(ValueError):
            preview_order(Broker(), **{**args, **invalid})


def test_scanner_input_diagnostic_distinguishes_missing_symbol_from_history():
    broker = Broker()
    import pandas as pd

    broker.candles = lambda *args, **kwargs: pd.DataFrame()
    result = scanner_input_checks(
        broker, symbols=["DUMMYHEG", "TCS"], mode="swing", period="2y", now=NOW
    )
    assert result["checks"][0]["error_code"] == "NSE_EQUITY_INSTRUMENT_NOT_FOUND"
    assert result["checks"][1]["error_code"] == "INSUFFICIENT_COMPLETED_HISTORY"
    assert result["broker_orders_allowed"] is False


def test_scanner_export_keeps_safe_failure_evidence_and_legacy_ui_explains_it():
    error = {
        "symbol": "HFCL",
        "signal": "ERROR",
        "error": "History unavailable",
        "error_code": "HISTORY_FAILED",
        "error_reference": "scan-123",
    }
    assert all(
        evidence_rows([error])[0][key] == error[key]
        for key in ("error", "error_code", "error_reference")
    )
    report = build_report(
        {
            "run_id": "legacy",
            "mode": "swing",
            "period": "2y",
            "strategy_id": "tf_ema9_26_bullish_pivot",
            "results": [
                {"symbol": "BIRET", "signal": "ERROR"},
                {
                    "symbol": "TCS",
                    "signal": "EXIT",
                    "execution_blocked_reason": (
                        "research_next_candle_execution_not_paper_enabled"
                    ),
                },
            ],
        },
        kind="scan",
    )
    app = AppTest.from_string(
        "from webapp.report_workspace import render_completed_report\n"
        "import streamlit as st\n"
        "render_completed_report(st.session_state['batch'])"
    )
    app.session_state["batch"] = {
        "batch_id": "legacy",
        "kind": "scan",
        "report": report,
    }
    app.run(timeout=15)
    assert not app.exception
    shown = app.dataframe[0].value
    assert "Legacy report" in shown.iloc[0]["error"]
    assert "use paper automation" in shown.iloc[1]["paper_action"]
    assert "execution_blocked_reason" not in shown


def test_render_boot_verifies_existing_book_holds_lock_and_forces_broker_off(
    book, monkeypatch
):
    from scripts.local_engine_runtime import exclusive_lock
    from services import render_paper_boot as boot
    from services.cloud_paper_storage import prepare_cloud_storage

    monkeypatch.setattr(os, "environ", os.environ.copy())
    prepare_cloud_storage(boot_id="a" * 32)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TRENDFORGE_CLOUD_PAPER_EXECUTION", "true")
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "true")
    monkeypatch.setattr(boot, "_PREPARED", False)
    with ExitStack() as locks:
        monkeypatch.setattr(boot, "_LOCK", locks)
        assert boot.prepare_render_paper() == "restart_verified"
        assert boot.prepare_render_paper() == "already_prepared"
        assert os.environ["TRENDFORGE_LIVE_TRADING_ENABLED"] == "false"
        assert os.environ["TRENDFORGE_STORAGE_RECOVERY_VERIFIED"] == "true"
        with (
            pytest.raises(RuntimeError),
            exclusive_lock(book.parent / "paper-cloud-runtime.lock"),
        ):
            pytest.fail("A second executor acquired the book")


def test_cloud_admission_blocks_overlap_and_stop_does_not_wait(monkeypatch):
    from services import cloud_workload_gate as gate

    monkeypatch.setenv("RENDER", "true")
    for registry in (gate._PAPER, gate._RESEARCH, gate._VALIDATION, gate._STARTING):
        registry.clear()
    begun, release, stopped = threading.Event(), threading.Event(), threading.Event()

    class Paper:
        @gate.paper_admission
        def configure(self, enabled):
            if enabled:
                begun.set()
                assert release.wait(5)
            else:
                stopped.set()

    @gate.research_admission
    def research(_self):
        return "allowed"

    paper = Paper()
    start = threading.Thread(target=paper.configure, args=(True,))
    start.start()
    try:
        assert begun.wait(3)
        with pytest.raises(gate.CloudWorkloadBusy):
            research(None)
        paper.configure(False)
        assert stopped.is_set()
    finally:
        release.set()
        start.join(3)
    assert research(None) == "allowed"
    manager = type("Manager", (), {})()
    manager._stopping = threading.Event()
    manager.futures = {"active": Future()}
    gate.register_research(manager)
    with pytest.raises(gate.CloudWorkloadBusy):
        paper.configure(True)
    manager.futures["active"].set_result(None)


def test_render_paper_requires_explicit_single_host_confirmation(monkeypatch):
    from tests.test_paper_controls_and_kite_preparation import scoped

    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "false")
    env = scoped()
    with pytest.raises(ValueError, match="PC"):
        env.service.configure(True)
    assert not env.service.status()["enabled"]
    env.service.configure(True, confirm_render_executor=True)
    assert env.service.status()["enabled"]
    env.service.configure(False)


def test_preview_and_input_routes_require_admin_and_redact_provider_errors(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.trading_workspace_router import attach_trading_workspace_routes

    admin = "market-preparation-test-admin-" * 3
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", admin)
    broker = Broker()
    factory = type("Factory", (), {"_default_kite": lambda self: broker})()
    app = FastAPI()
    attach_trading_workspace_routes(
        app,
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        provider_factory=factory,
    )
    payload = dict(
        symbol="TCS", side="BUY", product="MIS", quantity=1, stoploss=95, target=110
    )
    headers = {"X-TrendForge-Admin-Key": admin}
    with TestClient(app) as client:
        assert (
            client.post("/workspace/kite/order-preview", json=payload).status_code
            == 401
        )
        assert client.get("/workspace/scan-data-readiness").status_code == 401
        response = client.post(
            "/workspace/kite/order-preview",
            json={**payload, "place_order": True},
            headers=headers,
        )
        assert response.status_code == 422

        def failed():
            raise ValueError("secret-provider-response")

        broker.health = failed
        response = client.post(
            "/workspace/kite/order-preview", json=payload, headers=headers
        )
        assert response.status_code == 503
        assert "secret-provider-response" not in response.text


def test_campaign_cancellation_preserves_completed_children_and_stops_next_partition(
    technical, monkeypatch
):
    monkeypatch.setenv("RENDER", "false")
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "false")
    monkeypatch.setattr(
        "services.research_batches.research_partitions",
        lambda symbols, settings, strategies: [
            {"symbols": [symbol], "settings": settings} for symbol in symbols
        ],
    )
    from services.research_execution import execute_research

    entered, release = threading.Event(), threading.Event()
    calls = []

    def execute(*args):
        calls.append(args[1])
        entered.set()
        assert release.wait(5)
        return execute_research(*args)

    monkeypatch.setattr("services.research_execution.execute_research", execute)
    manager = ResearchBatchManager(technical, import_history=False, isolated=False)
    try:
        batch = manager.submit("backtest", request())
        assert entered.wait(3)
        manager.cancel(batch["batch_id"])
        release.set()
        result = finish(manager, batch)
        assert result["status"] == "interrupted" and result["report"] is None
        assert len(calls) == 1
        assert manager.repository.get(batch["batch_id"] + "-p002") is None
    finally:
        release.set()
        manager.close(wait=True)
