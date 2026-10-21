from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.app import create_app
from core.database import database_health, initialize_database
from database.repositories.strategy_runtime_state_repository import (
    StrategyRuntimeStateRepository,
)
from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner
from services.multi_strategy_validation_runtime import (
    _persist_validation,
    status as validation_status,
)
from services.strategy_runtime_reconciliation_service import (
    StrategyRuntimeReconciliationService,
)


def test_r7256_database_schema_and_execution_claim_are_restart_safe(
    tmp_path,
):
    path = tmp_path / "trendforge.db"
    initialize_database(str(path))
    health = database_health(str(path))
    assert health["status"] == "ready"

    first = StrategyRuntimeStateRepository(db_path=str(path))
    try:
        first.save_state(
            first.SCANNER_KEY,
            "scanner_snapshot",
            {
                "run_id": "scan-1",
                "status": "completed",
                "results": [],
                "strategy_summary": [],
            },
        )
        assert first.claim_execution(
            scan_run_id="scan-1",
            validation_run_id="validation-1",
            strategy_id="tpl_supertrend_rsi",
        ) is True
    finally:
        first.close()

    restarted = StrategyRuntimeStateRepository(db_path=str(path))
    try:
        saved = restarted.load_state(restarted.SCANNER_KEY)
        assert saved["payload"]["run_id"] == "scan-1"
        assert restarted.has_execution_claim(
            scan_run_id="scan-1",
            validation_run_id="validation-1",
            strategy_id="tpl_supertrend_rsi",
        ) is True
        assert restarted.claim_execution(
            scan_run_id="scan-1",
            validation_run_id="validation-1",
            strategy_id="tpl_supertrend_rsi",
        ) is False
        assert restarted.health()["status"] == "ready"
    finally:
        restarted.close()


class FakeStateRepository:
    def __init__(self, payload=None):
        self.payload = payload
        self.saved = []

    def load_state(self, key):
        if key == "r72.5.latest_scanner" and self.payload:
            return {"payload": self.payload}
        return None

    def save_state(self, key, state_type, payload):
        self.saved.append((key, state_type, dict(payload)))
        return {"state_key": key, "state_type": state_type, "payload": payload}


def _scanner_payload(run_id="scan-restored"):
    return {
        "status": "completed",
        "run_id": run_id,
        "universe": "NIFTY 100",
        "mode": "swing",
        "results": [],
        "strategy_summary": [],
        "top_picks": [],
    }


def test_r7256_scanner_restores_sqlite_snapshot_and_persists_exact_run(
    tmp_path,
):
    state = FakeStateRepository(_scanner_payload())
    scanner = MultiStrategyNiftyScanner(
        market_data=object(),
        state_repository=state,
    )
    scanner._snapshot_path = tmp_path / "scan.json"

    restored = scanner.results()
    assert restored["source"] == "sqlite_persistent"
    assert restored["last_result"]["run_id"] == "scan-restored"
    assert restored["snapshot_storage"] == "sqlite_persistent"

    payload = _scanner_payload("scan-new")
    scanner._store_snapshot(payload)
    keys = [row[0] for row in state.saved]
    assert "r72.5.latest_scanner" in keys
    assert "r72.5.scanner:scan-new" in keys


def test_r7256_validation_restores_from_sqlite_after_app_restart(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "validation.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    initialize_database(str(path))

    _persist_validation(
        {
            "status": "completed",
            "run_id": "validation-restart",
            "request": {"universes": ["NIFTY 100"]},
            "completed_at": "2026-10-21T10:00:00+05:30",
            "strategy_validation": [],
            "strategy_universe_metrics": [],
            "excluded_strategies": [],
            "progress": {
                "phase": "completed",
                "progress_pct": 100.0,
            },
        }
    )

    app = SimpleNamespace(state=SimpleNamespace())
    restored = validation_status(app)
    assert restored["status"] == "completed"
    assert restored["run_id"] == "validation-restart"
    assert restored["state_storage"] == "sqlite_persistent"
    assert restored["restart_safe"] is True

    repo = StrategyRuntimeStateRepository(db_path=str(path))
    try:
        exact = repo.load_state(
            "r72.5.validation:validation-restart"
        )
        assert exact["payload"]["run_id"] == "validation-restart"
    finally:
        repo.close()


def _strategy_position():
    return SimpleNamespace(
        strategy_id="tpl_supertrend_rsi",
        strategy_name="Template · Supertrend + RSI",
        trade_mode="swing",
        source_scan_run_id="scan-lineage",
        validation_run_id="validation-lineage",
    )


def test_r7256_reconciliation_verifies_exact_open_position_lineage(
    tmp_path,
):
    path = tmp_path / "reconcile.db"
    initialize_database(str(path))
    repo = StrategyRuntimeStateRepository(db_path=str(path))
    try:
        scan = {
            "status": "completed",
            "run_id": "scan-lineage",
            "universe": "NIFTY 100",
            "mode": "swing",
            "results": [],
            "strategy_summary": [],
        }
        validation = {
            "status": "completed",
            "run_id": "validation-lineage",
            "completed_at": "2026-10-21T10:00:00+05:30",
        }
        repo.save_state(
            repo.SCANNER_KEY,
            "scanner_snapshot",
            scan,
        )
        repo.save_state(
            "r72.5.scanner:scan-lineage",
            "scanner_run",
            scan,
        )
        repo.save_state(
            repo.VALIDATION_KEY,
            "validation_snapshot",
            validation,
        )
        repo.save_state(
            "r72.5.validation:validation-lineage",
            "validation_run",
            validation,
        )
        assert repo.claim_execution(
            scan_run_id="scan-lineage",
            validation_run_id="validation-lineage",
            strategy_id="tpl_supertrend_rsi",
        )

        paper = SimpleNamespace(
            runtime=SimpleNamespace(
                portfolio=SimpleNamespace(
                    positions={"TCS": _strategy_position()}
                )
            )
        )
        service = StrategyRuntimeReconciliationService(
            state_repository=repo,
            paper_service=paper,
        )
        result = service.reconciliation()

        assert result["status"] == "ready"
        assert result["open_strategy_positions"] == 1
        assert result["consistent_positions"] == 1
        assert result["incomplete_lineage_positions"] == 0
        row = result["positions"][0]
        assert row["scanner_run_persisted"] is True
        assert row["validation_run_persisted"] is True
        assert row["execution_claim_persisted"] is True
        assert row["lineage_status"] == "CONSISTENT"
        assert result["safety"]["broker_orders_allowed"] is False
    finally:
        repo.close()


class FakeReconciliation:
    def reconciliation(self):
        return {
            "status": "ready",
            "version": "R72.5.6-v1",
            "open_strategy_positions": 0,
            "consistent_positions": 0,
            "incomplete_lineage_positions": 0,
            "safety": {
                "read_only": True,
                "broker_orders_allowed": False,
            },
        }


class ApiFactory:
    def strategy_runtime_reconciliation_service(self):
        return FakeReconciliation()


def test_r7256_api_exposes_read_only_reconciliation():
    app = create_app(
        ApiFactory(),
        database_initializer=lambda: {
            "status": "initialized",
            "path": ":memory:",
        },
    )

    with TestClient(app) as client:
        response = client.get(
            "/paper/strategy-runtime/reconciliation"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "R72.5.6-v1"
    assert payload["safety"]["read_only"] is True
    assert payload["safety"]["broker_orders_allowed"] is False



def test_r7256_reconciliation_does_not_claim_restart_safety_on_ephemeral_storage(
    tmp_path,
):
    path = tmp_path / "ephemeral.db"
    initialize_database(str(path))
    repo = StrategyRuntimeStateRepository(db_path=str(path))
    try:
        paper = SimpleNamespace(
            runtime=SimpleNamespace(
                portfolio=SimpleNamespace(positions={})
            )
        )
        service = StrategyRuntimeReconciliationService(
            state_repository=repo,
            paper_service=paper,
            storage_health_getter=lambda: {
                "status": "ephemeral_or_unverified",
                "verified_persistent": False,
            },
        )
        result = service.reconciliation()

        assert result["status"] == "degraded"
        assert (
            result["restart_safety"]["durable_storage_verified"]
            is False
        )
        assert result["restart_safety"]["restart_safe"] is False
    finally:
        repo.close()
