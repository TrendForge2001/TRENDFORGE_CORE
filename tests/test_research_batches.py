"""Durable batch progress, automatic fill reports and bounded non-trading work."""

import base64
import csv
import hashlib
import io
import threading
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.research_reports_router import research_reports_router
from core.database import initialize_database
from database.repositories.backtest_results import BacktestResultsRepository
from database.repositories.research_batches import ResearchBatchRepository
from scanner.strategy_horizons import HORIZONS, horizon_strategies, horizon_strategy
from services.execution_report import ReportValidationError
from services.portfolio_backtest_service import PortfolioBacktestService
from services.research_batches import ResearchBatchManager, ResearchQueueFull
from services.research_report import build_report, csv_report
from tests.test_compact_backtesting import partial_result
from tests.test_three_stock_portfolio import STRATEGY, service


def request(**changes):
    return {
        "symbols": ["TCS", "SBIN"],
        "strategy_id": STRATEGY,
        "horizon": "short_term",
        "stock_list": "NIFTY 50",
        "short_borrow_available": False,
        **changes,
    }


@pytest.fixture
def technical(tmp_path):
    path = str(tmp_path / "research.db")
    initialize_database(path)
    value = service()
    value.repository = BacktestResultsRepository(db_path=path)
    yield value
    value.repository.close()


def finish(manager, batch):
    manager.futures[batch["batch_id"]].result(timeout=20)
    return manager.repository.get(batch["batch_id"])


def test_horizon_catalog_supports_daily_medium_long_and_quick_multiday_swing():
    assert list(HORIZONS) == [
        "intraday",
        "short_swing",
        "short_term",
        "medium_term",
        "long_term",
    ]
    for horizon in HORIZONS:
        choices = horizon_strategies(horizon)
        assert choices
        assert not {"tf_medium_ema50_100", "tf_long_ema100_200"} & {
            row["strategy_id"] for row in choices.values()
        }
        assert all(
            row["interval"]
            == (
                "15m"
                if horizon == "intraday"
                else "1wk"
                if row["strategy_id"] == "tf_weekly_gap_recovery_ema50_100_floor"
                else "1d"
            )
            for row in choices.values()
        )
    assert (
        horizon_strategy("short_swing", "tf_ema9_26_bullish_pivot")["mode"] == "swing"
    )
    assert (
        horizon_strategy("medium_term", "tf_ema50_100_bullish_pivot")["mode"] == "swing"
    )
    assert (
        horizon_strategy("long_term", "tf_ema100_200_bullish_pivot")["period"] == "5y"
    )
    with pytest.raises(ValueError):
        horizon_strategy("short_swing", "tf_ema100_200_bullish_pivot")


def test_direct_backtest_generates_and_saves_backend_report_before_return(technical):
    phases = []
    result = PortfolioBacktestService(technical).run(
        symbols=["TCS", "SBIN"],
        mode="swing",
        strategy_id=STRATEGY,
        progress=lambda phase, count: phases.append((phase, count)),
        report_horizon="short_term",
        report_stock_list="NIFTY 50",
    )
    assert phases == [
        ("history", 0),
        ("history", 2),
        ("indicators", 1),
        ("indicators", 2),
        ("simulation", 2),
        ("report", 2),
    ]
    report = technical.repository.by_run_id(result["run_id"])["result"]["report"]
    assert report == result["report"]
    from openpyxl import load_workbook

    workbook = load_workbook(
        io.BytesIO(base64.b64decode(report["xlsx_base64"])), read_only=True
    )
    sheet = workbook["Trade entries and exits"]
    values = list(sheet.values)
    assert values[0] == tuple(report["columns"]) and len(values) == 3
    workbook.close()
    rows = list(csv.DictReader(io.StringIO(report["csv"])))
    assert len(rows) == 2 and {row["symbol"] for row in rows} == {"TCS", "SBIN"}
    assert all(
        row["entry_at"] and row["exit_at"] and row["exit_reason"] for row in rows
    )
    assert report["report_type"] == "historical_backtest_exit_fills"
    assert (
        hashlib.sha256(report["csv"].encode("utf-8-sig")).hexdigest()
        == report["sha256"]
    )


def test_partial_exit_csv_preserves_every_actual_fill_and_source_policy():
    result = {
        **partial_result(),
        "run_id": "partial",
        "strategy_id": STRATEGY,
        "mode": "swing",
    }
    report = build_report(
        result, kind="backtest", horizon="short_term", stock_list="NIFTY 50"
    )
    rows = list(csv.DictReader(io.StringIO(report["csv"])))
    assert [int(row["quantity"]) for row in rows] == [5, 5]
    assert [float(row["exit_price"]) for row in rows] == [110, 120]
    assert sum(float(row["net_pnl"]) for row in rows) == 148
    assert {row["run_id"] for row in rows} == {"partial"}
    old = deepcopy(result)
    old["parameters"].update(deployment_limit=80000, cash_reserve=20000)
    with pytest.raises(ReportValidationError):
        build_report(old, kind="backtest")
    historical = build_report(old, kind="backtest", historical=True)
    assert historical["parameters"]["cash_reserve"] == 20000
    assert historical["registry_version"] == "unrecorded"
    result["exit_fills"].pop()
    with pytest.raises(ReportValidationError):
        build_report(result, kind="backtest")


def test_batches_remain_separate_and_reports_survive_reopening_database(technical):
    manager = ResearchBatchManager(technical, import_history=False)
    try:
        first = finish(manager, manager.submit("backtest", request()))
        second = finish(manager, manager.submit("backtest", request(symbols=["TCS"])))
        assert first["batch_id"] != second["batch_id"]
        assert first["status"] == second["status"] == "completed"
        assert first["report"]["rows"] != second["report"]["rows"]
        assert first["completed_symbols"] == 2 and second["completed_symbols"] == 1
        reopened = BacktestResultsRepository(db_path=technical.repository.db.db_path)
        try:
            saved = ResearchBatchRepository(reopened.db).get(first["batch_id"])
            assert saved["report"] == first["report"]
        finally:
            reopened.close()
    finally:
        manager.close(wait=True)


def test_queue_capacity_visible_progress_and_failures_do_not_publish_reports(
    technical, monkeypatch
):
    started, release = threading.Event(), threading.Event()

    def slow(_self, **kwargs):
        kwargs["progress"]("history", 1)
        started.set()
        assert release.wait(10)
        raise RuntimeError("provider exception with secret must not appear in batch")

    monkeypatch.setattr(PortfolioBacktestService, "run", slow)
    manager = ResearchBatchManager(technical, import_history=False)
    try:
        batches = [manager.submit("backtest", request())]
        assert started.wait(5)
        current = manager.repository.get(batches[0]["batch_id"])
        assert current["status"] == "running" and current["completed_symbols"] == 1
        batches += [manager.submit("backtest", request()) for _ in range(2)]
        assert batches[-1]["status"] == "queued"
        with pytest.raises(ResearchQueueFull):
            manager.submit("backtest", request())
        release.set()
        for batch in batches:
            failed = finish(manager, batch)
            assert failed["status"] == "failed" and failed["report"] is None
            assert failed["error_code"] == "research_batch_failed"
            assert "secret" not in str(failed)
    finally:
        release.set()
        manager.close(wait=True)


def test_restart_marks_unfinished_batches_interrupted_and_never_replays(technical):
    repo = ResearchBatchRepository(technical.repository.db)
    repo.create("unfinished", "backtest", request())
    repo.start("unfinished")
    manager = ResearchBatchManager(technical, import_history=False)
    try:
        saved = repo.get("unfinished")
        assert saved["status"] == "interrupted" and saved["report"] is None
        assert saved["error_code"] == "runtime_restarted"
        assert manager.futures == {}
        assert repo.finish("unfinished", {"rows": []}) is False
    finally:
        manager.close(wait=True)


def test_scanner_report_is_labelled_evidence_and_never_executes_paper(technical):
    calls = []

    def scan(**kwargs):
        calls.append(kwargs)
        kwargs["progress"]("scan", 2)
        return {
            "run_id": kwargs["run_id"],
            "mode": kwargs["mode"],
            "strategy_id": kwargs["strategy_id"],
            "results": [{"symbol": "TCS", "signal": "WAIT", "score": 0}],
        }

    technical.scan = scan
    manager = ResearchBatchManager(technical, import_history=False)
    try:
        batch = finish(manager, manager.submit("scan", request()))
        assert batch["status"] == "completed"
        assert batch["report"]["report_type"] == "scanner_indicator_snapshot"
        assert "exit_at" not in batch["report"]["columns"]
        assert calls[0]["execute_paper"] is False
        assert not technical.repository.latest()
    finally:
        manager.close(wait=True)


def test_short_borrow_assumption_and_horizon_are_enforced_before_queueing(technical):
    manager = ResearchBatchManager(technical, import_history=False)
    try:
        with pytest.raises(ValueError, match="borrow"):
            manager.submit(
                "backtest",
                request(
                    horizon="medium_term", strategy_id="tf_ema50_100_bearish_pivot"
                ),
            )
        with pytest.raises(ValueError, match="horizon"):
            manager.submit("backtest", request(horizon="long_term"))
        assert not manager.repository.latest()
    finally:
        manager.close(wait=True)


def test_csv_formula_strings_are_escaped_but_numeric_losses_are_preserved():
    content = csv_report(
        [{"symbol": "=HYPERLINK(1)", "net_pnl": -20}], ["symbol", "net_pnl"]
    )
    row = next(csv.DictReader(io.StringIO(content)))
    assert row["symbol"].startswith("'=") and row["net_pnl"] == "-20"


def test_reports_api_requires_admin_validates_scope_and_downloads_generated_csv(
    technical, monkeypatch
):
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "research-test-admin-" * 3)
    app = FastAPI()
    app.include_router(research_reports_router(app, lambda: technical))
    headers = {"X-TrendForge-Admin-Key": "research-test-admin-" * 3}
    with TestClient(app) as client:
        for path in (
            "/reports/batches",
            "/reports/summary",
            "/reports/storage",
            "/reports/batches/missing",
            "/reports/batches/missing/report.csv",
            "/reports/batches/missing/report.xlsx",
        ):
            assert client.get(path).status_code == 401
        assert client.post("/reports/backtest", json=request()).status_code == 401
        for change in (
            {"capital": 200000},
            {"execute_paper": True},
            {"horizon": "other"},
            {"short_borrow_available": "true"},
            {"stock_list": "FAKE"},
        ):
            assert (
                client.post(
                    "/reports/backtest", json=request(**change), headers=headers
                ).status_code
                == 422
            )
        response = client.post("/reports/backtest", json=request(), headers=headers)
        assert response.status_code == 202
        batch_id = response.json()["batch_id"]
        manager = app.state.research_batches
        manager.futures[batch_id].result(timeout=20)
        detail = client.get("/reports/batches/" + batch_id, headers=headers).json()
        assert detail["status"] == "completed"
        summary = client.get("/reports/summary", headers=headers).json()
        assert summary["latest_completed"]["backtest"]["batch_id"] == batch_id
        assert summary["latest_completed"]["scan"] is None
        assert summary["storage"]["pc_sync_connected"] is False
        csv_response = client.get(
            "/reports/batches/" + batch_id + "/report.csv", headers=headers
        )
        assert csv_response.status_code == 200
        assert csv_response.content == detail["report"]["csv"].encode("utf-8-sig")
        excel_response = client.get(
            "/reports/batches/" + batch_id + "/report.xlsx", headers=headers
        )
        assert excel_response.status_code == 200
        assert excel_response.content == base64.b64decode(
            detail["report"]["xlsx_base64"]
        )
        assert (
            "report"
            not in client.get("/reports/batches", headers=headers).json()["batches"][0]
        )
        assert client.get(
            "/reports/batches", params={"offset": 100}, headers=headers
        ).json() == {"batches": []}
        assert (
            client.get("/reports/batches/missing", headers=headers).status_code == 404
        )
        manager.close(wait=True)
