"""Backtest equivalence, stage progress and report recovery from PC files."""

import json
from copy import deepcopy

import pytest
from streamlit.testing.v1 import AppTest

from backtest.ema_pivot_engine import EmaPivotBacktestEngine
from core.database import initialize_database
from database.repositories.research_batches import ResearchBatchRepository
from scanner.multi_strategy_engine import MultiStrategyEngine
from services.research_archive import ResearchArchive
from services.research_batches import ResearchBatchManager
from services.research_capacity import validate_backtest_capacity
from tests.test_ema_pivot_backtests import execution_frame
from tests.test_ema_pivot_scanners import IDS
from tests.test_research_batches import finish, request


@pytest.fixture
def technical(tmp_path):
    from database.repositories.backtest_results import BacktestResultsRepository
    from tests.test_three_stock_portfolio import service

    path = str(tmp_path / "research.db")
    initialize_database(path)
    value = service()
    value.repository = BacktestResultsRepository(db_path=path)
    yield value
    value.repository.close()


class ReferenceEngine:
    def __init__(self):
        self.engine = MultiStrategyEngine()

    def evaluate(self, *args, **kwargs):
        return self.engine.evaluate(*args, **kwargs)


@pytest.mark.parametrize("strategy_id", IDS)
@pytest.mark.parametrize("mode", ["swing", "intraday"])
def test_fast_path_preserves_every_fill_cost_and_equity_observation(strategy_id, mode):
    frames = {
        symbol: execution_frame(strategy_id, intraday=mode == "intraday")
        for symbol in ["TCS", "SBIN", "ITC"]
    }
    args = {
        "strategy_id": strategy_id,
        "mode": mode,
        "interval": "15m" if mode == "intraday" else "1d",
        "short_borrow_available": True,
    }
    expected = EmaPivotBacktestEngine(strategy_engine=ReferenceEngine()).run(
        frames, **args
    )
    progress = []
    actual = EmaPivotBacktestEngine().run(
        frames, **args, progress=lambda done, total: progress.append((done, total))
    )
    assert actual == expected
    assert (
        progress[0][0] == 1
        and progress[-1] == (len(next(iter(frames.values()))) - 1,) * 2
    )


def test_progress_records_bar_work_and_preserves_symbol_counts(technical):
    repo = ResearchBatchRepository(technical.repository.db)
    repo.create("progress", "backtest", request())
    repo.start("progress")
    repo.progress("progress", "indicators", 2)
    repo.progress("progress", "simulation", 40, 500)
    saved = repo.get("progress")
    assert saved["completed_symbols"] == 2
    assert saved["phase_completed"] == 40 and saved["phase_total"] == 500
    assert saved["updated_at"] >= saved["started_at"]
    initialize_database(technical.repository.db.db_path)
    assert repo.get("progress")["phase_total"] == 500


def test_completed_reports_have_csv_excel_and_restore_without_rerunning(technical):
    manager = ResearchBatchManager(technical, import_history=False)
    batch = finish(manager, manager.submit("backtest", request()))
    assert batch["status"] == "completed"
    files = manager.archive._target(batch["batch_id"])
    assert {p.name for p in files.iterdir()} == {
        "batch.json",
        "report.csv",
        "report.xlsx",
    }
    assert (files / "report.csv").read_bytes() == batch["report"]["csv"].encode(
        "utf-8-sig"
    )
    manager.close(wait=True)
    technical.repository.db.execute("DELETE FROM research_batches")
    technical.market_data.batch_candles_with_errors = lambda *args, **kwargs: (
        pytest.fail("Restoring reports must not fetch market data")
    )
    restored = ResearchBatchManager(technical, import_history=False)
    try:
        saved = restored.repository.get(batch["batch_id"])
        assert restored.archive_recovery == {"restored": 1, "invalid": 0}
        assert (
            saved["report"] == batch["report"]
            and saved["created_at"] == batch["created_at"]
        )
        assert restored.futures == {}
    finally:
        restored.close(wait=True)


def test_report_committed_to_files_recovers_after_interrupted_database_publish(
    technical, monkeypatch
):
    manager = ResearchBatchManager(technical, import_history=False)
    original = manager.repository.finish
    monkeypatch.setattr(manager.repository, "finish", lambda *args: False)
    batch = finish(manager, manager.submit("backtest", request()))
    assert batch["status"] == "running"
    assert (manager.archive._target(batch["batch_id"]) / "batch.json").is_file()
    monkeypatch.setattr(manager.repository, "finish", original)
    manager.close(wait=True)
    restored = ResearchBatchManager(technical, import_history=False)
    try:
        assert restored.repository.get(batch["batch_id"])["status"] == "completed"
        assert restored.archive_recovery["restored"] == 1
        assert not restored.futures
    finally:
        restored.close(wait=True)


def test_corrupt_archive_does_not_replace_or_invent_a_report(technical):
    manager = ResearchBatchManager(technical, import_history=False)
    batch = finish(manager, manager.submit("backtest", request()))
    file = manager.archive._target(batch["batch_id"]) / "batch.json"
    manager.close(wait=True)
    corrupted = deepcopy(batch)
    corrupted["report"]["rows"][0]["net_pnl"] = 999999
    file.write_text(json.dumps(corrupted))
    technical.repository.db.execute("DELETE FROM research_batches")
    restored = ResearchBatchManager(technical, import_history=False)
    try:
        assert restored.repository.get(batch["batch_id"]) is None
        assert restored.archive_recovery == {"restored": 0, "invalid": 1}
    finally:
        restored.close(wait=True)


def test_pc_archive_failure_is_explicit_and_retains_database_evidence(
    technical, monkeypatch
):
    manager = ResearchBatchManager(technical, import_history=False)
    monkeypatch.setattr(
        manager.archive,
        "save",
        lambda *args: (_ for _ in ()).throw(OSError("private path")),
    )
    try:
        batch = finish(manager, manager.submit("backtest", request()))
        assert (
            batch["status"] == "failed"
            and batch["error_code"] == "report_archive_failed"
        )
        assert batch["report"] is None and "private path" not in str(batch)
        assert technical.repository.by_run_id(batch["batch_id"])["result"]["report"]
    finally:
        manager.close(wait=True)


def test_cloud_capacity_rejects_large_work_without_truncating_or_restricting_pc(
    monkeypatch,
):
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "true")
    validate_backtest_capacity({"period": "2y"}, 251)
    with pytest.raises(ValueError, match="PC workspace"):
        validate_backtest_capacity({"period": "5y"}, 1000)
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "false")
    validate_backtest_capacity({"period": "5y"}, 1000)


def test_cold_report_deeplink_uses_main_signin_and_six_pages(monkeypatch):
    from pathlib import Path

    from streamlit.runtime.pages_manager import PagesManager

    monkeypatch.setattr(PagesManager, "uses_pages_directory", None)
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "ui-test-access-" * 3)
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "ui-test-backend-" * 3)
    monkeypatch.setattr(
        "webapp.runtime.api_client",
        lambda **kwargs: pytest.fail("Unauthenticated page cannot read reports"),
    )
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "streamlit_app.py").run(timeout=15)
    assert not app.exception and PagesManager.uses_pages_directory is False
    app.switch_page("webapp/pages/reports.py").run(timeout=15)
    assert not app.exception and not app.dataframe and not app.get("download_button")
    assert any(item.label == "Webapp access key" for item in app.text_input)


def test_backup_script_copies_only_existing_completed_reports(technical, tmp_path):
    from scripts.save_research_reports import copy_reports

    manager = ResearchBatchManager(technical, import_history=False)
    batch = finish(manager, manager.submit("backtest", request()))
    manager.close(wait=True)
    calls = []

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_content(self, size):
            yield json.dumps(self.payload).encode()

    class Session:
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/reports/batches"):
                return Response(
                    {
                        "batches": [
                            {"batch_id": batch["batch_id"], "status": "completed"},
                            {"status": "running"},
                        ]
                    }
                )
            assert url.endswith("/reports/batches/" + batch["batch_id"])
            return Response(batch)

    archive = ResearchArchive(tmp_path / "copied")
    assert copy_reports(
        "https://cloud.test", archive, admin_key="test-header", session=Session()
    ) == {"saved": 1, "unfinished": 1}
    assert (
        archive.read(archive._target(batch["batch_id"]) / "batch.json")["report"]
        == batch["report"]
    )
    assert all(row[1]["allow_redirects"] is False for row in calls)
