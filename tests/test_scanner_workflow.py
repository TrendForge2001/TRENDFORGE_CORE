"""Research routing, retention, password encryption and independent paper state."""

import base64
import hashlib
import io
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import msoffcrypto
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from api.scanner_workflow_router import scanner_workflow_router
from core.database import initialize_database
from core.report_access import encrypted_excel, kite_token, kite_unlocked
from database.database import Database
from database.repositories.research_batches import ResearchBatchRepository
from providers.nse_all_index_members import parse_members
from services.research_archive import ResearchArchive
from services.research_report import build_report, csv_report, excel_report
from services.research_storage import complete_batch
from services.scanner_workflow import ScannerBacktestDispatcher, ScannerWorkflow
from services.scanner_workflow_export import (
    backtest_view,
    export_job,
    export_pending_queue,
    profitability,
)

STRATEGY = "tf_swing_ema20_50_rsi_volume"
OWNER = "synthetic-owner-password-for-workflow-tests"


@pytest.fixture
def repository(tmp_path):
    path = str(tmp_path / "book.db")
    initialize_database(path)
    db = Database(path)
    yield ResearchBatchRepository(db)
    db.close()


def scan(repository, key, *, strategy=STRATEGY, parent=None, at=None, archive=None):
    request = {
        "horizon": "short_term",
        "strategy_id": strategy,
        "stock_list": "NIFTY 50",
        "symbols": ["BUYCO", "EXITCO", "WAITCO", "BADCO"],
    }
    if parent:
        request["parent_batch_id"] = parent
    repository.create(key, "scan", request)
    repository.start(key)
    report = build_report(
        {
            "run_id": key,
            "strategy_id": strategy,
            "mode": "swing",
            "interval": "1d",
            "period": "2y",
            "results": [
                {
                    "symbol": symbol,
                    "signal": signal,
                    "side": "LONG",
                    "score": 80,
                    "entry": 100,
                    "stoploss": 95,
                    "target2": 110,
                    "data_status": "UNAVAILABLE" if signal == "ERROR" else "READY",
                    "indicators": {},
                    "error": "source unavailable" if signal == "ERROR" else None,
                }
                for symbol, signal in (
                    ("BUYCO", "BUY"),
                    ("EXITCO", "EXIT"),
                    ("WAITCO", "WAIT"),
                    ("BADCO", "ERROR"),
                )
            ],
        },
        kind="scan",
        horizon="short_term",
        stock_list="NIFTY 50",
    )
    if at:
        report["generated_at"] = at
    assert complete_batch(repository, archive, key, report)
    return repository.get(key)


def backtest(repository, key, request):
    repository.create(key, "backtest", request)
    repository.start(key)
    rows = [
        {
            "symbol": request["symbols"][0],
            "strategy_id": request["strategy_id"],
            "entry_at": "2026-10-01T09:15:00+05:30",
            "exit_at": "2026-10-05T09:15:00+05:30",
            "entry_price": 100,
            "exit_price": 112,
            "quantity": 10,
            "gross_pnl": 120,
            "pnl": 118,
        }
    ]
    columns = list(rows[0])
    csv = csv_report(rows, columns)
    workbook = excel_report(
        rows, columns, {"strategy_id": request["strategy_id"]}, kind="backtest"
    )
    report = {
        "run_id": key,
        "report_type": "historical_backtest_exit_fills",
        "rows": rows,
        "columns": columns,
        "csv": csv,
        "sha256": hashlib.sha256(csv.encode("utf-8-sig")).hexdigest(),
        "xlsx_base64": base64.b64encode(workbook).decode(),
        "xlsx_sha256": hashlib.sha256(workbook).hexdigest(),
        "metrics": {"net_profit": 118, "total_trades": 1},
        "generated_at": datetime.now(UTC).isoformat(),
    }
    repository.finish(key, report)
    return repository.get(key)


def test_scan_completion_queues_only_actionable_stocks_with_strategy(repository):
    scan(repository, "scan-one")
    workflow = ScannerWorkflow(repository)
    rows = workflow.queue()
    assert {row["symbol"] for row in rows} == {"BUYCO", "EXITCO"}
    assert {row["strategy_id"] for row in rows} == {STRATEGY}
    assert {row["stock_list"] for row in rows} == {"NIFTY 50"}
    assert {row["origin_signal"] for row in rows} == {"BUY", "EXIT"}
    assert len(workflow.report("scan-one")["rows"]) == 4
    workflow.reconcile()
    assert len(workflow.queue()) == 2


def test_retention_keeps_ten_runs_and_preserves_queue_and_backtests(
    repository, tmp_path
):
    archive = ResearchArchive(tmp_path / "archives")
    start = datetime(2026, 11, 1, tzinfo=UTC)
    for i in range(12):
        scan(
            repository,
            f"scan-{i:02}",
            at=(start + timedelta(days=i)).isoformat(),
            archive=archive,
        )
    workflow = ScannerWorkflow(repository, archive)
    assert len(workflow.reports()) == 10
    assert len(workflow.queue()) == 24
    assert repository.get("scan-00")["report"] is None
    assert not archive._target("scan-00").exists()
    assert "scan-00" in archive.retired_scans()
    assert len(list(archive.root.glob("*/batch.json"))) == 10
    # A recovery pass cannot resurrect a report already removed by retention.
    assert archive.restore(repository)["restored"] == 0
    request = {
        "horizon": "short_term",
        "strategy_id": STRATEGY,
        "stock_list": "NIFTY 50",
        "symbols": ["BUYCO"],
    }
    original = backtest(repository, "protected-backtest", request)
    assert repository.get("protected-backtest")["report"] == original["report"]
    with pytest.raises(KeyError):
        workflow.report("scan-00")


def test_password_encryption_requires_real_password_to_open(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", OWNER)
    book = Workbook()
    book.active.append(["Strategy", "Net P&L"])
    book.active.append([STRATEGY, 118])
    plain = io.BytesIO()
    book.save(plain)
    protected = encrypted_excel(plain.getvalue())
    assert not protected.startswith(b"PK")
    document = msoffcrypto.OfficeFile(io.BytesIO(protected))
    assert document.is_encrypted()
    with pytest.raises(msoffcrypto.exceptions.InvalidKeyError):
        document.load_key(password="wrong-password", verify_password=True)
    document.load_key(password=OWNER, verify_password=True)
    decoded = io.BytesIO()
    document.decrypt(decoded)
    assert load_workbook(decoded).active["B2"].value == 118
    assert encrypted_excel(protected) == protected


def test_kite_unlock_expires_and_password_rotation_invalidates_it(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", OWNER)
    token = kite_token(OWNER, now=100)
    assert kite_unlocked(token, now=101)
    assert not kite_unlocked(token, now=1000)
    assert not kite_unlocked(token + "broken", now=101)
    with pytest.raises(ValueError):
        kite_token("wrong", now=100)
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", OWNER + "-rotated")
    assert not kite_unlocked(token, now=101)


def test_dispatcher_runs_queue_once_and_export_preserves_original_trades(
    repository, monkeypatch
):
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", OWNER)
    scan(repository, "origin")
    submissions = []

    def submit(kind, request):
        assert kind == "backtest"
        assert request["short_borrow_available"] is False
        submissions.append(request)
        return backtest(repository, "result-one", request)

    manager = SimpleNamespace(repository=repository, archive=None, submit=submit)
    dispatcher = ScannerBacktestDispatcher(manager)
    dispatcher.start()
    dispatcher.thread.join(timeout=5)
    dispatcher.start()
    dispatcher.thread.join(timeout=5)
    assert len(submissions) == 1
    assert submissions[0]["symbols"] == ["BUYCO", "EXITCO"]
    jobs = dispatcher.workflow.jobs()
    assert jobs[0]["status"] == "completed"
    assert profitability(dispatcher.workflow, jobs[0]) == "Profitable · ₹118.00 net"
    encrypted = export_job(dispatcher.workflow, jobs[0]["job_id"])
    document = msoffcrypto.OfficeFile(io.BytesIO(encrypted))
    document.load_key(password=OWNER)
    stream = io.BytesIO()
    document.decrypt(stream)
    workbook = load_workbook(stream, read_only=True)
    queued = list(workbook["Queued stock strategies"].values)
    assert "strategy_id" in queued[0]
    assert len(queued) == 3
    assert any("Trade entries" in sheet for sheet in workbook.sheetnames)
    trades = next(sheet for sheet in workbook if "Trade entries" in sheet.title)
    assert list(trades.values)[1][3] == "2026-10-05T09:15:00+05:30"


def test_workflow_api_requires_admin_and_exposes_saved_reports(repository, monkeypatch):
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY", "test-workflow-admin-key-000000000000000000"
    )
    scan(repository, "saved")
    manager = SimpleNamespace(
        repository=repository, archive=None, _control=threading.Lock()
    )
    app = FastAPI()
    app.include_router(scanner_workflow_router(lambda: manager), prefix="/reports")
    client = TestClient(app)
    assert client.get("/reports/scanner-runs").status_code == 401
    headers = {"X-TrendForge-Admin-Key": "test-workflow-admin-key-000000000000000000"}
    assert (
        client.get("/reports/scanner-runs", headers=headers).json()["retention"][
            "completed_scanner_runs"
        ]
        == 10
    )
    assert (
        len(client.get("/reports/scanner-runs/saved", headers=headers).json()["rows"])
        == 4
    )
    result = client.get("/reports/backtest-queue", headers=headers).json()
    assert result["pending_stocks"] == 2
    assert result["strategies"][0]["strategy_id"] == STRATEGY


def test_nse_membership_rejects_wrong_index_and_partial_payload():
    payload = {
        "name": "NIFTY CHEMICALS",
        "advance": {"advances": "1", "declines": "0", "unchanged": "0"},
        "data": [
            {"symbol": "NIFTY CHEMICALS"},
            {
                "symbol": "EXAMPLE",
                "meta": {"symbol": "EXAMPLE", "companyName": "Example Ltd"},
            },
        ],
    }
    assert parse_members(payload, "NIFTY CHEMICALS")[0]["symbol"] == "EXAMPLE"
    with pytest.raises(ValueError):
        parse_members(payload, "NIFTY 500")
    payload["advance"]["advances"] = "2"
    with pytest.raises(ValueError):
        parse_members(payload, "NIFTY CHEMICALS")


def test_backtesting_page_only_displays_strategy_and_profitability(monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    calls = []

    class Client:
        def get_json(self, path, **kwargs):
            assert path == "/reports/backtest-queue"
            return {
                "strategies": [
                    {"strategy": "Swing EMA 20/50", "profitability": "₹118.00 net"}
                ],
                "jobs": [],
                "pending_stocks": 2,
            }

        def post_json(self, path, payload, **kwargs):
            calls.append((path, payload))
            return {"status": "started"}

    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: Client())
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "webapp/pages/kite_backtesting.py"
    ).run(timeout=15)
    assert not app.exception
    assert list(app.dataframe[0].value.columns) == ["Strategy", "Profitability"]
    assert not app.selectbox and not app.text_input and not app.number_input
    next(
        button for button in app.button if button.label == "Backtest queued stocks"
    ).click().run(timeout=15)
    assert calls == [("/reports/backtest-queue/start", {})]


def test_locked_kite_window_does_not_request_account_data(monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    calls = []

    class Client:
        def get_json(self, path, **kwargs):
            calls.append(path)
            return {"status": "ready", "authenticated": True}

    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", OWNER)
    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: Client())
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "webapp/pages/live_kite.py"
    ).run(timeout=15)
    assert not calls
    app.text_input[0].set_value("wrong")
    next(b for b in app.button if b.label == "Unlock Kite window").click().run(
        timeout=15
    )
    assert not calls and app.text_input[0].value == ""
    app.text_input[0].set_value(OWNER)
    next(b for b in app.button if b.label == "Unlock Kite window").click().run(
        timeout=15
    )
    assert calls == ["/workspace/kite-session"]
    assert (
        "tf_kite_window_password" not in app.session_state
        or app.session_state["tf_kite_window_password"] == ""
    )
    app.session_state["tf_kite_window_token"] = "expired"
    app.run(timeout=15)
    assert calls == ["/workspace/kite-session"]


def test_excel_password_is_required_without_plaintext_fallback(monkeypatch):
    monkeypatch.delenv("TRENDFORGE_EXCEL_PASSWORD", raising=False)
    monkeypatch.delenv("TRENDFORGE_WEBAPP_ACCESS_KEY", raising=False)
    with pytest.raises(ValueError, match="Configure"):
        encrypted_excel(b"anything")


def test_partitioned_scans_preserve_each_strategy_in_queue(repository):
    from services.research_partitions import partition_manifest

    parent = "multi-strategy-scan"
    request = {
        "horizon": "short_term",
        "strategy_id": STRATEGY,
        "stock_list": "NIFTY 50",
        "symbols": ["BUYCO", "EXITCO", "WAITCO", "BADCO"],
        "settings": {"mode": "swing", "period": "2y"},
    }
    repository.create(parent, "scan", request)
    repository.start(parent)
    children = [
        scan(repository, parent + "-p1", parent=parent),
        scan(
            repository,
            parent + "-p2",
            strategy="tf_swing_vwma9_26_rsi_volume",
            parent=parent,
        ),
    ]
    assert complete_batch(
        repository, None, parent, partition_manifest(parent, "scan", request, children)
    )
    workflow = ScannerWorkflow(repository)
    assert len(workflow.reports()) == 1
    assert len(workflow.report(parent)["rows"]) == 8
    assert len(workflow.queue()) == 4
    assert {row["strategy_id"] for row in workflow.queue()} == {
        STRATEGY,
        "tf_swing_vwma9_26_rsi_volume",
    }


def test_paper_admission_block_leaves_queue_available(repository):
    from services.cloud_workload_gate import CloudWorkloadBusy

    scan(repository, "paper-busy-origin")
    paper = {"enabled": True}

    def blocked(*args, **kwargs):
        raise CloudWorkloadBusy("Research is paused while paper automation is active")

    dispatcher = ScannerBacktestDispatcher(
        SimpleNamespace(repository=repository, archive=None, submit=blocked)
    )
    dispatcher.start()
    dispatcher.thread.join(timeout=5)
    assert all(row["job_id"] is None for row in dispatcher.workflow.queue())
    assert dispatcher.workflow.jobs()[0]["status"] == "blocked"
    assert paper["enabled"] is True


def test_pre_upgrade_scans_outside_ten_runs_are_retired(repository):
    for i in range(12):
        scan(
            repository,
            f"legacy-{i:02}",
            at=(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i)).isoformat(),
        )
    # Simulate a database created before the handoff journal existed.
    repository.db.execute("DELETE FROM scanner_workflow_runs")
    repository.db.execute("DELETE FROM scanner_retired_runs")
    # Restore old payloads cleared during fixture creation.
    source = repository.get("legacy-02")["report"]
    import json

    for i in (0, 1):
        repository.db.execute(
            "UPDATE research_batches SET report_json=?,error_code=NULL "
            "WHERE batch_id=?",
            (json.dumps(source), f"legacy-{i:02}"),
        )
    workflow = ScannerWorkflow(repository)
    assert len(workflow.reports()) == 10
    assert repository.get("legacy-00")["report"] is None
    assert repository.get("legacy-01")["report"] is None


def test_pending_queue_workbook_and_fingerprint(repository, monkeypatch):
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", OWNER)
    workflow = ScannerWorkflow(repository)
    before = backtest_view(workflow)["queue_fingerprint"]
    scan(repository, "pending-export")
    after = backtest_view(workflow)["queue_fingerprint"]
    assert before != after
    protected = export_pending_queue(workflow)
    document = msoffcrypto.OfficeFile(io.BytesIO(protected))
    document.load_key(password=OWNER, verify_password=True)
    stream = io.BytesIO()
    document.decrypt(stream)
    rows = list(load_workbook(stream, read_only=True).active.values)
    assert len(rows) == 3
    assert rows[0][1] == "strategy_name"
    assert {row[0] for row in rows[1:]} == {"BUYCO", "EXITCO"}


@pytest.mark.parametrize(
    "pnl,trades,label",
    [
        (0, 0, "No trades"),
        (0, 1, "Flat"),
        (-20, 1, "Loss-making"),
    ],
)
def test_profitability_distinguishes_idle_flat_and_losing(
    repository,
    pnl,
    trades,
    label,
):
    batch = backtest(
        repository,
        "profit-categories",
        {
            "horizon": "short_term",
            "strategy_id": STRATEGY,
            "symbols": ["BUYCO"],
            "stock_list": "NIFTY 50",
        },
    )
    report = batch["report"]
    report["metrics"] = {"net_profit": pnl, "total_trades": trades}
    import json

    repository.db.execute(
        "UPDATE research_batches SET report_json=? WHERE batch_id=?",
        (json.dumps(report), batch["batch_id"]),
    )
    assert profitability(
        ScannerWorkflow(repository),
        {
            "batch_id": batch["batch_id"],
            "status": "completed",
        },
    ).startswith(label)
