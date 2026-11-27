"""The same historical submission and bounded diagnostics on UI and operator paths."""

import json
import secrets
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.research_reports_router import research_reports_router
from api.scanner_error_boundary import install_api_error_boundary
from services.research_batches import ResearchBatchManager
from services.research_campaign import request_research_campaign
from tests.test_research_batches import technical  # noqa: F401


def test_selected_campaign_uses_validated_route_and_is_consumed_once(
    technical, monkeypatch
):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-db1tb7jncjis73c994e0")
    symbols = [f"STOCK{i}" for i in range(50)]
    monkeypatch.setattr(
        "services.research_campaign.official_symbols", lambda _: symbols
    )
    options = {
        "strategy_id": "tf_ema100_200_bullish_pivot",
        "horizon": "long_term",
        "risk_fraction": 0.006,
        "slippage_bps": 4,
        "initial_capital": 125000,
        "max_positions": 2,
        "cost_bps": 11,
        "move_stop_after_partial": False,
    }
    monkeypatch.setenv(
        "TRENDFORGE_RESEARCH_CAMPAIGN",
        json.dumps(
            {
                "request_id": "selected-test",
                "stock_list": "NIFTY 50",
                "period": "5y",
                "backtest": options,
            }
        ),
    )
    app = FastAPI()
    manager = ResearchBatchManager(technical, import_history=False, isolated=False)
    monkeypatch.setattr(manager, "_run", lambda *args: None)
    app.include_router(
        research_reports_router(
            app, lambda: technical, manager_factory=lambda _: manager
        )
    )
    try:
        (batch_id,) = request_research_campaign(app)
        saved = manager.repository.get(batch_id)
        assert saved["kind"] == "backtest"
        assert options.items() <= saved["request"].items()
        assert saved["request"]["account_scope"] == "one_shared_account"
        assert saved["request"]["symbols"] == symbols
        assert "partitions" not in saved["request"]
        assert request_research_campaign(app) is None
    finally:
        manager.close(wait=True)


def test_failed_submission_has_safe_correlated_reason(technical, monkeypatch, caplog):
    admin = secrets.token_hex(32)
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", admin)
    app = FastAPI()
    install_api_error_boundary(app)
    manager = ResearchBatchManager(technical, import_history=False, isolated=False)
    app.include_router(
        research_reports_router(
            app, lambda: technical, manager_factory=lambda _: manager
        )
    )

    def fail(*args):
        error = sqlite3.OperationalError("private failure body")
        error.sqlite_errorname = "SQLITE_FULL"
        raise error

    monkeypatch.setattr(manager.repository, "create", fail)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/reports/backtest",
                headers={"X-TrendForge-Admin-Key": admin},
                json={
                    "stock_list": "NIFTY 50",
                    "symbols": ["EXAMPLE"],
                    "horizon": "long_term",
                    "strategy_id": "tf_ema100_200_bullish_pivot",
                },
            )
        assert response.status_code == 503
        assert response.json()["reference"] in caplog.text
        assert "SQLITE_FULL" in caplog.text
        assert "private failure body" not in caplog.text + response.text
    finally:
        manager.close(wait=True)
