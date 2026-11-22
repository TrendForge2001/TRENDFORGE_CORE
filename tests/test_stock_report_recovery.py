"""Real scanner/report contracts and expected preview blockers, without a broker."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.scanner_error_boundary import install_api_error_boundary
from api.trading_workspace_router import attach_trading_workspace_routes
from core.database import initialize_database
from database.repositories.backtest_results import BacktestResultsRepository
from services.institutional_stock_rating import (
    assess_technical,
    rate,
    technical_evidence,
)
from services.stock_report_service import StockReportService
from services.technical_trading_service import TechnicalTradingService
from webapp.stock_report_document import document

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 22, 22, tzinfo=TZ)


def history():
    index = pd.bdate_range("2021-11-01", "2026-11-20", tz="Asia/Kolkata")
    x = np.arange(len(index))
    close = 100 + x * 0.015 + np.sin(x / 3) * 0.3
    frame = pd.DataFrame(
        {
            "open": close - 0.02,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )
    frame.loc["2025-01-02", "high"] = 160
    frame.loc["2025-01-03", "low"] = 60
    return frame


class Market:
    def __init__(self, frame):
        self.frame, self.calls = frame, []

    def batch_candles_with_errors(self, symbols, *, interval, period):
        self.calls.append((interval, period))
        return {symbol: self.frame.copy() for symbol in symbols}, {}

    def candles(self, symbol, **kwargs):
        # Weekly strategy's benchmark request remains legitimate. Stock-report
        # charts must use the exact completed scanner frame, without refetching.
        assert symbol == "NIFTY 100", "Duplicate report candle fetch"
        return self.frame.copy()


@pytest.fixture
def real_service(tmp_path):
    path = str(tmp_path / "reports.db")
    initialize_database(path)
    market = Market(history())
    technical = TechnicalTradingService(
        market_data=market,
        repository=BacktestResultsRepository(db_path=path),
    )
    notifications = []
    technical.paper_auto_entry = SimpleNamespace(
        process_scan=lambda *a, **k: notifications.append(k),
    )
    reports = StockReportService(
        lambda: technical,
        company_provider=SimpleNamespace(
            get=lambda *a, **k: {"status": "unavailable", "metrics": {}},
        ),
    )
    yield technical, reports, market, notifications
    technical.repository.close()


@pytest.mark.parametrize("horizon", ["short_term", "long_term"])
def test_real_report_keeps_technical_component_when_institutional_trades_missing(
    real_service, horizon
):
    technical, reports, market, notifications = real_service
    report = reports.build("EXAMPLE", horizon=horizon, now=NOW)
    assert report["market_error"] is None
    assert report["price"]["bar_date"] == "2026-11-20"
    assert len(report["candles"]) == 252
    assert len(market.calls) == 1
    assert report["technical_assessment"]["status"] == "READY"
    assert 0 <= report["technical_assessment"]["score"] <= 60
    assert report["rating"]["rating"] == "INSUFFICIENT_DATA"
    assert report["rating"]["score"] is None
    assert report["trade_plan"]["conditions"]
    assert report["trade_plan"]["indicator_references"]
    assert "No matched actual institutional trade data" in document(report)
    assert "Technical component:" in document(report)
    assert "/60" in document(report)
    assert notifications == []
    assert not report["broker_orders_allowed"]
    assert "_report_evidence" not in report["technical"]
    if horizon == "long_term":
        assert report["trade_plan"]["targets"][0] is not None
    else:
        assert report["trade_plan"]["targets"] == [None, None, None]


@pytest.mark.parametrize("horizon", ["short_term", "long_term"])
def test_technical_component_is_identical_to_existing_combined_rating_math(
    real_service, horizon
):
    _, _, market, _ = real_service
    evidence = technical_evidence(market.frame, horizon=horizon, now=NOW)
    activity = {
        "avg_buy": 300,
        "avg_sell": 100,
        "observations": 2,
        "data_coverage": "COMPLETE_INPUT",
        "metric": "quantity",
        "period_start": "2026-11-20",
        "period_end": "2026-11-20",
    }
    combined = rate(activity, evidence, horizon=horizon, now=NOW)
    component = assess_technical(evidence, horizon=horizon, now=NOW)
    assert combined["technical_score"] is not None
    assert combined["technical_score"] == component["score"]
    assert combined["technical_points"] == component["points"]


def test_stale_scan_is_not_hidden_by_research_execution_block(real_service):
    _, reports, market, notifications = real_service
    market.frame = market.frame.iloc[:-1]
    report = reports.build("EXAMPLE", now=NOW)
    assert report["technical"]["data_status"] == "STALE"
    assert report["market_error"]["data_code"] == "CANDLES_STALE"
    assert report["technical_assessment"]["status"] == "UNAVAILABLE"
    assert report["trade_plan"]["status"] == "DATA_UNAVAILABLE"
    assert not report["trade_plan"]["reviewable_setup"]
    assert notifications == []


def test_invalid_yearly_entry_plan_explains_wait_without_inventing_targets(
    real_service,
):
    _, reports, market, _ = real_service
    market.frame.iloc[
        -1, market.frame.columns.get_indexer(["open", "high", "low", "close"])
    ] = [399, 401, 398, 400]
    report = reports.build("EXAMPLE", horizon="long_term", now=NOW)
    assert report["trade_plan"]["status"] == "NO_VALID_ENTRY_PLAN"
    assert report["trade_plan"]["entry"] is None
    assert report["trade_plan"]["targets"] == [None, None, None]
    assert report["trade_plan"]["indicator_references"]["FIB_YEAR_R1"] < 400
    assert not report["trade_plan"]["reviewable_setup"]
    assert "No valid entry plan at the latest completed close" in document(report)


@pytest.mark.parametrize(
    "horizon,strategy_id",
    [
        ("short_term", "tf_swing_ema20_50_rsi_volume"),
        ("short_term", "tf_swing_vwma9_26_rsi_volume"),
        ("short_term", "tf_ema20_50_bullish_pivot"),
        ("short_term", "tf_daily_vwma20_50_rsi_fibonacci_yearly"),
        ("long_term", "tf_weekly_gap_recovery_ema50_100_floor"),
        ("long_term", "tf_medium_ema50_100"),
        ("long_term", "tf_long_ema100_200"),
        ("long_term", "tf_ema50_100_bullish_pivot"),
        ("long_term", "tf_ema100_200_bullish_pivot"),
    ],
)
def test_each_active_report_strategy_returns_canonical_evidence(
    real_service,
    horizon,
    strategy_id,
):
    _, reports, _, notifications = real_service
    report = reports.build("EXAMPLE", horizon=horizon, strategy_id=strategy_id, now=NOW)
    assert report["market_error"] is None
    assert report["technical"]["signal"] != "ERROR"
    assert report["price"]["bar_date"] == "2026-11-20"
    assert report["technical_assessment"]["status"] == "READY"
    assert report["strategy"]["entry_rules"]
    assert report["strategy"]["stoploss_rules"]
    assert report["trade_plan"]["conditions"]
    assert notifications == []


def test_closed_session_quote_returns_specific_blocker_instead_of_service_outage(
    monkeypatch,
):
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY", "test-preview-admin-key-00000000000000000000"
    )
    from tests.test_kite_preview_form import Broker

    class ClosedSessionBroker(Broker):
        def quote(self, symbols):
            stamp = datetime.now(TZ) - timedelta(days=3)
            return {
                key: {"last_price": 100, "timestamp": stamp.isoformat()}
                for key in symbols
            }

    app = FastAPI()
    install_api_error_boundary(app)
    attach_trading_workspace_routes(
        app,
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        provider_factory=SimpleNamespace(_default_kite=lambda: ClosedSessionBroker()),
    )
    client = TestClient(app)
    response = client.post(
        "/workspace/kite/order-preview",
        headers={
            "X-TrendForge-Admin-Key": "test-preview-admin-key-00000000000000000000",
        },
        json={
            "symbol": "EXAMPLE",
            "side": "BUY",
            "product": "CNC",
            "quantity": 1,
            "stoploss": 95,
            "target": 110,
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error_code"] == "QUOTE_STALE"
    assert detail["orders_submitted"] == 0
    assert "Outside trading hours" in detail["message"]
    assert "SERVICE_UNAVAILABLE" not in response.text
