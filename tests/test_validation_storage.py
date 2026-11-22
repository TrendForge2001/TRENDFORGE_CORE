"""Lossless storage recovery, mixed legacy rows and same-policy resumption."""

import asyncio
import gzip
import json
import sqlite3
import zlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient

from database.repositories.strategy_runtime_state_repository import (
    StrategyRuntimeStateRepository,
)
from scanner.strategy_registry import REGISTRY_VERSION
from services.paper_operator_request import BASE_CHECKS, run_paper_operator_request
from services.validation_journal import (
    ValidationJournal,
    decode_rows,
    export_headers,
    write_result,
)
from services.validation_storage import (
    _digest,
    compact_journal,
    recover_storage,
    storage_report,
)
from tests.test_aligned_research_policy import book as book


def legacy(tmp_path, run="original"):
    saved = ValidationJournal(
        run, {"saved_policy": "unchanged"}, REGISTRY_VERSION, root=tmp_path
    )
    for index in range(25):
        rows = [
            dict(
                symbol=f"S{index}",
                evidence="repeated-indicator-evidence" * 500,
                net_pnl=index - 15,
            )
        ]
        saved.connection.execute(
            "INSERT INTO units VALUES(?,?,?,?,?,?,?,?)",
            ("swing", f"S{index}", json.dumps(rows), json.dumps(rows), "[]", 1, 1, 0),
        )
    saved.connection.commit()
    saved.close()
    return saved.path


def test_compaction_retains_every_payload_cutoff_and_ledger(tmp_path):
    path = legacy(tmp_path)
    with sqlite3.connect(path) as original:
        expected = _digest(original)
        metadata = original.execute("SELECT payload FROM meta").fetchone()[0]
    result = compact_journal(path)
    assert result["changed"] and result["bytes_after"] < result["bytes_before"] / 4
    assert result["units"] == 25 and result["row_counts"] == [25, 25, 0]
    restored = ValidationJournal(
        "original", {"saved_policy": "unchanged"}, REGISTRY_VERSION, root=tmp_path
    )
    try:
        assert _digest(restored.connection) == expected
        assert (
            restored.connection.execute("SELECT payload FROM meta").fetchone()[0]
            == metadata
        )
        assert len(restored.completed()) == 25
        assert sum(r["net_pnl"] for r in restored.rows["trades"]) == sum(
            i - 15 for i in range(25)
        )
        restored.rows["trades"].append({"symbol": "NEW", "net_pnl": 7})
        restored.commit_unit("swing", "NEW")
        assert len(restored.completed()) == 26
        assert len(restored.rows["trades"]) == 26
        assert isinstance(
            restored.connection.execute("SELECT trades FROM units LIMIT 1").fetchone()[
                0
            ],
            bytes,
        )
        assert Path(path).stat().st_mode & 0o777 == 0o600
    finally:
        restored.close()


def test_mixed_legacy_and_compressed_units_remain_readable(tmp_path):
    legacy(tmp_path)
    saved = ValidationJournal(
        "original", {"saved_policy": "unchanged"}, REGISTRY_VERSION, root=tmp_path
    )
    saved.rows["trades"].append({"symbol": "NEW", "net_pnl": 7})
    saved.commit_unit("intraday", "NEW")
    assert len(list(saved.rows["trades"])) == 26
    assert {
        type(r[0]) for r in saved.connection.execute("SELECT trades FROM units")
    } == {str, bytes}
    saved.close()


def test_interrupted_replacement_retains_original_bytes(tmp_path, monkeypatch):
    path = legacy(tmp_path)
    before = path.read_bytes()

    def fail(*args):
        raise OSError("replacement failed")

    monkeypatch.setattr("services.validation_storage.os.replace", fail)
    with pytest.raises(OSError, match="replacement failed"):
        compact_journal(path)
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".compact").exists()


def test_low_staging_headroom_does_not_modify_original(tmp_path, monkeypatch):
    path = legacy(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(
        "services.validation_storage.shutil.disk_usage",
        lambda _: SimpleNamespace(free=1024),
    )
    with pytest.raises(OSError, match="headroom"):
        compact_journal(path)
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".compact").exists()


def test_unknown_schema_is_preserved(tmp_path):
    path = legacy(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Unsupported journal"):
        compact_journal(path)
    assert path.read_bytes() == before


def test_storage_counts_hardlinks_once_and_recovery_never_changes_reports(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "paper.db"))
    root = tmp_path / "validation"
    path = legacy(root)
    other = tmp_path / "completed-report.json"
    other.write_text("saved baseline report")
    link = tmp_path / "baseline-archive.json"
    link.hardlink_to(other)
    totals = storage_report(tmp_path)
    assert (
        sum(totals["logical_bytes"].values())
        == path.stat().st_size + other.stat().st_size
    )
    result = recover_storage("original")
    assert result["sufficient_headroom"]
    assert result["current_checkpoint"]["units"] == 25
    assert other.read_text() == link.read_text() == "saved baseline report"


def test_compressed_export_streams_and_http_download_decodes_json(tmp_path):
    report = {"trades": [{"symbol": "SAMPLE", "net_pnl": 3}] * 2000}
    path = tmp_path / "result.json"
    write_result(path, report, compressed=True)
    assert path.stat().st_size < len(json.dumps(report)) / 10
    assert json.loads(gzip.decompress(path.read_bytes())) == report
    app = FastAPI()

    @app.get("/export")
    def download():
        return FileResponse(
            path, media_type="application/json", headers=export_headers(path)
        )

    with TestClient(app) as client:
        response = client.get("/export")
        assert response.headers["content-encoding"] == "gzip"
        assert response.json() == report
    write_result(path, report)
    assert export_headers(path) == {} and json.loads(path.read_text()) == report


def test_corrupt_compressed_row_fails_closed():
    with pytest.raises(zlib.error):
        decode_rows(b"not a compressed journal row")


@pytest.mark.parametrize(
    "change", [None, "changed_policy", "old_cutoff", "running", "changed_borrow"]
)
def test_recovery_operator_preserves_saved_request_and_never_arms_paper(
    book, monkeypatch, change
):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TRENDFORGE_CLOUD_PAPER_EXECUTION", "true")
    now = datetime.now(UTC)
    repository = StrategyRuntimeStateRepository(db_path=str(book.path / "paper.db"))
    requests, starts = [], []
    config = dict(
        universe="NIFTY 500",
        target_symbols=None,
        target_strategy_ids=None,
        assume_short_borrow=True,
        control_generation=0,
        enabled=False,
        paper_only=True,
        broker_orders_allowed=False,
        account_policy={"capital": 100000},
    )
    request = dict(
        universes=["NIFTY 500"],
        modes=["positional", "swing"],
        source="all",
        strategy_ids=None,
        limit=None,
        capital=100000,
        chunk_size=5,
        force_refresh_universes=False,
        admission_policy=deepcopy(book.policy),
        shared_book=True,
        assume_short_borrow=True,
        evaluation_as_of=(now - timedelta(days=1)).isoformat(),
    )
    snapshot = dict(
        status="failed",
        checkpointed=True,
        worker_alive=False,
        run_id="saved-run",
        registry_version=REGISTRY_VERSION,
        request=request,
        as_of=request["evaluation_as_of"],
        progress={"processed_symbol_modes": 925, "total_symbol_modes": 1503},
    )
    if change == "changed_policy":
        request["admission_policy"]["minimum_rr"] = 3
    if change == "old_cutoff":
        snapshot["as_of"] = (now - timedelta(days=8)).isoformat()
    if change == "running":
        snapshot["status"], snapshot["worker_alive"] = "running", True
    if change == "changed_borrow":
        request["assume_short_borrow"] = False
    automation = SimpleNamespace(
        repository=repository,
        CONFIG_KEY="paper.automation.config.v1",
        status=lambda: config,
        bridge=SimpleNamespace(paper_auto_entry=book.auto),
        configure=lambda *args, **kwargs: starts.append(args),
    )
    command = dict(
        id="d" * 32,
        action="recover_corrected_research",
        registry_version=REGISTRY_VERSION,
        authorized_at=(now - timedelta(seconds=1)).isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(),
        confirm_render_executor=True,
    )

    def start(payload):
        requests.append(payload)
        return dict(status="running", run_id="saved-run")

    try:
        asyncio.run(
            run_paper_operator_request(
                json.dumps(command),
                automation_getter=lambda: automation,
                validation_getter=lambda: snapshot,
                validation_starter=start,
                readiness=lambda: {"checks": dict.fromkeys(BASE_CHECKS, True)},
                clock=lambda: now,
            )
        )
        assert not starts and config["enabled"] is False
        if change is None:
            assert requests == [{**request, "compact_checkpoints": True}]
            receipt = repository.load_state("paper.operator:" + command["id"])[
                "payload"
            ]
            assert receipt["preserved_processed_symbol_modes"] == 925
        else:
            assert not requests
    finally:
        repository.close()


@pytest.mark.parametrize("interrupted", [False, True])
def test_runtime_compacts_then_resumes_exact_saved_run(book, monkeypatch, interrupted):
    from services import multi_strategy_validation_runtime as runtime
    from services.validation_storage import recover_storage as real_recovery

    root = book.path / "validation"
    path = legacy(root)
    with sqlite3.connect(path) as connection:
        meta = json.loads(connection.execute("SELECT payload FROM meta").fetchone()[0])
    app = FastAPI()
    app.state.r7253_validation = dict(
        status="interrupted" if interrupted else "failed",
        registry_version=REGISTRY_VERSION,
        checkpointed=True,
        run_id="original",
        request=meta["request"],
        as_of=meta["as_of"],
        compact_checkpoints_pending=interrupted,
        progress={"processed_symbol_modes": 25, "total_symbol_modes": 26},
    )
    recoveries = []

    def recovery(run):
        result = real_recovery(run)
        recoveries.append(result)
        return result

    class Service:
        def __init__(self, **kwargs):
            pass

        def run(self, *, checkpoint, run_id, **kwargs):
            assert run_id == "original" and checkpoint.metadata == meta
            assert len(checkpoint.completed()) == 25
            assert isinstance(
                checkpoint.connection.execute(
                    "SELECT trades FROM units LIMIT 1"
                ).fetchone()[0],
                bytes,
            )
            checkpoint.rows["trades"].append({"symbol": "NEW", "net_pnl": 7})
            checkpoint.commit_unit("intraday", "NEW")
            return dict(
                status="completed",
                registry_version=REGISTRY_VERSION,
                trades=checkpoint.rows["trades"],
                errors=checkpoint.rows["errors"],
            )

    monkeypatch.setattr("services.validation_storage.recover_storage", recovery)
    monkeypatch.setattr(runtime, "MultiStrategyValidationService", Service)
    target = book.path / "finished.json"
    monkeypatch.setattr(runtime, "output_path", lambda: target)
    request = {
        **meta["request"],
        **({} if interrupted else {"compact_checkpoints": True}),
    }
    runtime.start_validation(app, scanner_service=object(), request=request)
    app.state.r7253_validation["_thread"].join(timeout=10)
    assert app.state.r7253_validation["status"] == "completed"
    assert app.state.r7253_validation["run_id"] == "original"
    assert app.state.r7253_validation["request"] == meta["request"]
    assert len(recoveries) == 1 and recoveries[0]["current_checkpoint"]["units"] == 25
    assert len(json.loads(target.read_text())["trades"]) == 26
