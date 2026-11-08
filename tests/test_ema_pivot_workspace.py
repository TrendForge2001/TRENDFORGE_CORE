"""Existing-screen access, API flow and restart-safe historical result storage."""

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from api.app import create_app
from core.database import initialize_database
from database.repositories.backtest_results import BacktestResultsRepository
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from services.portfolio_backtest_service import PortfolioBacktestService
from services.technical_trading_service import TechnicalTradingService
from tests.test_ema_pivot_backtests import execution_frame
from tests.test_ema_pivot_scanners import IDS
from webapp.backtest_pnl import build_backtest_pnl
from webapp.portfolio_backtesting import validate_result

ROOT = Path(__file__).resolve().parents[1]


def research_service(strategy_id, path):
    initialize_database(str(path))
    raw = execution_frame(strategy_id)
    data = pd.concat([raw.iloc[:1]] * 65 + [raw], ignore_index=True)
    data.index = pd.bdate_range("2026-01-05", periods=len(data), tz="Asia/Kolkata")
    market = SimpleNamespace(
        candles=lambda *a, **k: data.copy(),
        batch_candles_with_errors=lambda stocks, **k: (
            {s: data.copy() for s in stocks},
            {},
        ),
    )
    return TechnicalTradingService(
        market_data=market,
        repository=BacktestResultsRepository(db_path=str(path)),
        indicator_engine=SimpleNamespace(calculate=lambda f: f),
    )


@pytest.mark.parametrize("strategy_id", IDS)
def test_research_portfolio_results_and_partial_fill_ledger_survive_reopening(
    strategy_id, tmp_path
):
    path = tmp_path / "research.db"
    service = research_service(strategy_id, path)
    result = PortfolioBacktestService(service).run(
        symbols=["TCS", "SBIN", "INFY"],
        mode="swing",
        strategy_id=strategy_id,
        short_borrow_available=True,
        run_id="persisted-research",
    )
    validate_result(result)
    assert result["metrics"]["total_trades"] == 3
    assert result["engine"]["name"] == "EmaPivotBacktestEngine"
    assert result["safety"]["paper_orders_created"] is False
    service.repository.close()
    reopened = BacktestResultsRepository(db_path=str(path))
    saved = reopened.by_run_id("persisted-research")["result"]
    assert (
        reopened.by_run_id("persisted-research")["strategy_version"]
        == result["engine"]["version"]
    )
    assert saved["exit_fills"] == result["exit_fills"]
    assert saved["metrics"] == result["metrics"]
    reopened.close()


def test_single_stock_backtest_uses_real_symbol_and_saves_new_execution_model(tmp_path):
    service = research_service(IDS[0], tmp_path / "single.db")
    result = service.backtest(symbol="TCS", mode="swing", strategy_id=IDS[0])
    assert result["trades"] and result["exit_fills"]
    assert all(row["symbol"] == "TCS" for row in result["exit_fills"])
    assert result["strategy"]["stop_atr_reference"] == 1.5
    assert result["engine"]["name"] == "EmaPivotBacktestEngine"
    assert service.repository.by_run_id(result["run_id"])["result"] == result
    pnl = build_backtest_pnl([result])
    assert len(pnl["daily"]) == len({leg["exit_at"] for leg in result["exit_fills"]})
    assert (
        service.repository.by_run_id(result["run_id"])["strategy_version"]
        == result["engine"]["version"]
    )
    service.repository.close()


def test_short_assumption_and_positional_mode_flow_through_the_admin_api(
    tmp_path, monkeypatch
):
    key = "ema-workspace-test-admin-" * 3
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", key)
    strategy_id = IDS[-1]
    service = research_service(strategy_id, tmp_path / "api.db")
    client = TestClient(
        create_app(SimpleNamespace(technical_trading_service=lambda: service))
    )
    payload = {"symbols": ["TCS"], "strategy_id": strategy_id, "mode": "positional"}
    assert client.post("/technical/portfolio-backtest", json=payload).status_code == 401
    headers = {"X-TrendForge-Admin-Key": key}
    denied = client.post("/technical/portfolio-backtest", json=payload, headers=headers)
    assert denied.status_code == 422 and "borrow" in denied.text
    result = client.post(
        "/technical/portfolio-backtest",
        json={**payload, "short_borrow_available": True},
        headers=headers,
    )
    assert result.status_code == 200, result.text
    assert result.json()["parameters"]["short_borrow_assumed"] is True
    assert result.json()["safety"]["broker_orders_allowed"] is False
    service.repository.close()


@pytest.mark.parametrize("page", ["technical_scanner.py", "kite_backtesting.py"])
def test_eight_new_scanners_are_selectable_on_existing_screens(page, monkeypatch):
    from scanner.strategy_horizons import HORIZONS, horizon_strategies

    class Client:
        def get_json(self, path, **kwargs):
            return {"rows": [{"symbol": "TCS", "sector": "IT"}]}

    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: Client())
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    app = AppTest.from_file(ROOT / "webapp/pages" / page).run(timeout=15)
    key = "backtest" if page == "kite_backtesting.py" else "scanner"
    found = set()
    for horizon, label in HORIZONS.items():
        app.session_state[key + "_horizon"] = label
        app.run(timeout=15)
        assert not app.exception and len(app.selectbox) == 2
        assert app.selectbox[0].label == label + " strategy"
        choices = horizon_strategies(horizon)
        assert app.selectbox[0].options == list(choices)
        found.update(row["strategy_id"] for row in choices.values())
    assert set(EMA_PIVOT_SETUPS) <= found
    assert not app.radio and not app.checkbox
