from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.database import initialize_database
from database.repositories.strategy_runtime_state_repository import (
    StrategyRuntimeStateRepository,
)
from scanner.strategy_registry import REGISTRY_VERSION
from services.multi_strategy_validation_runtime import _persist_validation, status


def test_r7253_runtime_status_excludes_private_thread_object():
    app = FastAPI()
    app.state.r7253_validation = {
        "status": "running",
        "run_id": "r7253-test",
        "_thread": threading.Thread(),
        "progress": {"phase": "backtest", "progress_pct": 10.0},
    }

    payload = status(app)

    assert "_thread" not in payload
    assert payload["worker_alive"] is False
    assert payload["status"] == "running"


@pytest.mark.parametrize("old_version", [None, "ema-pivot-staged-paper-v6-adx-dm-ties"])
def test_faulty_window_validation_is_invalidated_but_retained_for_audit(
    monkeypatch, tmp_path, old_version
):
    database = tmp_path / "owner.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    initialize_database(str(database))
    payload = {
        "status": "completed",
        "run_id": "before-history-correction",
        "registry_version": old_version,
        "strategy_validation": [{"promotion_status": "ELIGIBLE_FOR_REVIEW"}],
    }
    _persist_validation(payload)
    output = tmp_path / "stale-validation.json"
    output.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("TRENDFORGE_R7253_OUTPUT_PATH", str(output))
    report = status(SimpleNamespace(state=SimpleNamespace()))
    assert report["status"] == "invalidated"
    assert report["required_registry_version"] == REGISTRY_VERSION
    assert report["restart_safe"] is False
    assert report["output_exists"] is False
    assert "strategy_validation" not in report
    repository = StrategyRuntimeStateRepository(db_path=str(database))
    try:
        saved = repository.load_state("r72.5.validation:before-history-correction")
        assert saved["payload"] == payload
    finally:
        repository.close()


def test_invalidated_validation_cannot_be_exported_as_current(monkeypatch, tmp_path):
    from api.app import create_app

    output = tmp_path / "stale-validation.json"
    output.write_text('{"status":"completed"}', encoding="utf-8")
    monkeypatch.setenv("TRENDFORGE_R7253_OUTPUT_PATH", str(output))
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "test-admin-key" * 4)
    app = create_app(SimpleNamespace())
    app.state.r7253_validation = {"status": "invalidated", "run_id": "stale"}
    client = TestClient(app)
    response = client.get(
        "/technical/multi-strategy/validation/export",
        headers={"X-TrendForge-Admin-Key": "test-admin-key" * 4},
    )
    assert response.status_code == 404
