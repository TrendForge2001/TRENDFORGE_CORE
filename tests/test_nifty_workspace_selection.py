"""Universe batching, sector widgets and scanner/backtest strategy consistency."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from api.app import create_app
from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
from providers.nse_broad_market_constituents import (
    INDEX_CONFIGS,
    NSEBroadMarketConstituentProvider,
    normalize_index_name,
)
from scanner.technical_strategy import strategy_profile
from scanner.workspace_strategies import strategy_choices, workspace_signal
from services.technical_trading_service import (
    TechnicalTradingService,
    TechnicalTradingValidationError,
)
from webapp.api_client import ApiError
from webapp.nifty_selection import scan_nifty_stocks


class ScanClient:
    def __init__(self):
        self.calls = []
        self.fail_chunk = None

    def post_json(self, path, payload, **kwargs):
        self.calls.append(payload)
        if len(self.calls) == self.fail_chunk:
            raise ApiError("private upstream response", status_code=503)
        return {
            "status": "completed",
            "mode": payload["mode"],
            "strategy_id": payload["strategy_id"],
            "run_id": payload["run_id"],
            "results": [
                {"symbol": s, "score": 75, "signal": "HOLD"} for s in payload["symbols"]
            ],
        }


def test_large_universe_is_scored_without_truncation_and_failures_are_not_zeroes():
    client = ScanClient()
    client.fail_chunk = 2
    symbols = [f"STOCK{i}" for i in range(250)]
    result = scan_nifty_stocks(
        client,
        {"symbols": symbols, "index": "NIFTY LARGEMIDCAP 250"},
        mode="swing",
        period="2y",
        strategy_id=None,
    )
    assert [len(req["symbols"]) for req in client.calls] == [100, 100, 50]
    assert len({req["run_id"] for req in client.calls}) == 3
    assert all(req["execute_paper"] is False for req in client.calls)
    assert [row["symbol"] for row in result["results"]] == symbols
    assert result["completed_symbols"] == 150
    assert result["error_symbols"] == 100
    assert result["results"][100]["score"] is None
    assert "private" not in str(result)


def test_auth_failure_aborts_scan_without_fabricating_scores():
    class Unauthorized:
        def post_json(self, *args, **kwargs):
            raise ApiError("Invalid administrative API key", status_code=401)

    with pytest.raises(ApiError) as failure:
        scan_nifty_stocks(
            Unauthorized(),
            {"symbols": ["TCS"]},
            mode="swing",
            period="2y",
            strategy_id=None,
        )
    assert failure.value.status_code == 401


def test_official_sector_membership_validation_and_aliases(tmp_path):
    csv = "Company Name,Industry,Symbol,Series,ISIN Code\n" + "\n".join(
        f"Bank {i},Banking,BANK{i},EQ,IN{i}" for i in range(12)
    )

    class Session:
        headers = {}

        def get(self, url, **kwargs):
            return SimpleNamespace(
                text=csv,
                headers={"content-type": "text/csv"},
                raise_for_status=lambda: None,
            )

    assert normalize_index_name("Bank Nifty") == "NIFTY BANK"
    assert normalize_index_name("Nifty FinNifty") == "NIFTY FINANCIAL SERVICES"
    assert "NIFTY IT" in INDEX_CONFIGS
    provider = NSEBroadMarketConstituentProvider(session=Session(), cache_dir=tmp_path)
    payload = provider.load("Bank Nifty")
    assert payload["count"] == 12
    assert all(row["sector"] == "Banking" for row in payload["members"])
    csv = "Company Name,Industry,Symbol\nTruncated,Banking,ONE\n"
    provider = NSEBroadMarketConstituentProvider(
        session=Session(), cache_dir=tmp_path / "new"
    )
    with pytest.raises(RuntimeError):
        provider.load("NIFTY BANK")


def candles(mode):
    stamps = pd.date_range(
        "2026-01-01 09:15",
        periods=70,
        freq="15min" if mode == "intraday" else "D",
        tz="Asia/Kolkata",
    )
    fast = [95.0] * 70
    fast[10:15] = [101.0] * 5
    return pd.DataFrame(
        {
            "open": 101.0,
            "high": 102.0,
            "low": 100.0,
            "close": 101.0,
            "volume": 2000.0,
            "EMA_20": fast,
            "EMA_50": 100.0,
            "VWMA_9": fast,
            "VWMA_26": 100.0,
            "RSI_14": 65.0,
            "VOL_SMA_20": 1000.0,
            "ATR": 2.0,
        },
        index=stamps,
    )


class Repository:
    def __init__(self):
        self.rows = {}

    def by_run_id(self, run_id):
        return self.rows.get(run_id)

    def save(self, row):
        self.rows[row["run_id"]] = row


@pytest.mark.parametrize("mode", ["intraday", "swing"])
@pytest.mark.parametrize("family", ["ema20_50", "vwma9_26"])
def test_named_scan_and_backtest_use_same_registered_rules(mode, family):
    strategy_id = f"tf_{mode}_{family}_rsi_volume"
    frame = candles(mode)

    class Market:
        def candles(self, *args, **kwargs):
            return frame.copy()

        def batch_candles_with_errors(self, symbols, **kwargs):
            return {s: frame.copy() for s in symbols}, {}

    class Indicators:
        def calculate(self, value):
            return value.copy()

    service = TechnicalTradingService(
        market_data=Market(), repository=Repository(), indicator_engine=Indicators()
    )
    now = datetime(2026, 10, 24, tzinfo=ZoneInfo("Asia/Kolkata"))
    scan = service.scan(symbols=["TCS"], mode=mode, strategy_id=strategy_id, now=now)
    expected_signal = workspace_signal(frame, strategy_profile(mode), strategy_id)
    assert scan["results"][0]["score"] == expected_signal["score"]
    assert scan["results"][0]["signal"] == expected_signal["signal"]
    result = service.backtest(
        symbol="TCS",
        mode=mode,
        strategy_id=strategy_id,
        capital=100000,
        cost_bps=12,
        slippage_bps=5,
        now=now,
    )
    expected = MultiStrategyBacktestEngine().run(
        frame,
        strategy_id=strategy_id,
        mode=mode,
        interval=strategy_profile(mode).interval,
        initial_capital=100000,
        cost_bps=12,
        slippage_bps=5,
    )
    assert result["metrics"] == expected.metrics
    assert result["trades"] == expected.trades
    assert result["metrics"]["total_trades"] > 0
    assert result["strategy_id"] == strategy_id
    assert result["safety"]["paper_orders_created"] is False
    with pytest.raises(TechnicalTradingValidationError):
        service.scan(
            symbols=["TCS"],
            mode=mode,
            strategy_id=strategy_id,
            execute_paper=True,
            now=now,
        )


def test_api_forwards_named_strategy_and_rejects_unknown_strategy():
    calls = []

    class Service:
        def scan(self, **kwargs):
            calls.append(kwargs)
            return {"status": "completed"}

        backtest = scan

    factory = SimpleNamespace(technical_trading_service=lambda: Service())
    client = TestClient(create_app(factory))
    for path, symbol in [
        ("scan", {"symbols": ["TCS"]}),
        ("backtest", {"symbol": "TCS"}),
    ]:
        response = client.post(
            "/technical/" + path,
            json={
                **symbol,
                "mode": "swing",
                "strategy_id": "tf_swing_ema20_50_rsi_volume",
            },
        )
        assert response.status_code == 200
        assert calls[-1]["strategy_id"] == "tf_swing_ema20_50_rsi_volume"
    service = TechnicalTradingService(market_data=object(), repository=Repository())
    with pytest.raises(TechnicalTradingValidationError):
        service.scan(symbols=["TCS"], mode="swing", strategy_id="unknown")


def test_sector_dropdown_changes_selection_and_removes_manual_entry(monkeypatch):
    class Client:
        def get_json(self, path, **kwargs):
            return {
                "rows": [
                    {"symbol": "TCS", "sector": "IT"},
                    {"symbol": "SBIN", "sector": "Banking"},
                ]
            }

    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: Client())
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "webapp/pages/technical_scanner.py").run(timeout=15)
    assert not app.exception
    assert not app.text_area
    strategy = next(w for w in app.selectbox if w.label == "Scanner / strategy")
    assert strategy.options == list(strategy_choices("intraday"))
    sector = next(w for w in app.selectbox if w.label == "Sector / industry")
    sector.set_value("Banking").run(timeout=15)
    assert not app.exception
    assert any("1 selected stocks" in c.value for c in app.caption)
    app.checkbox[0].check().run(timeout=15)
    assert app.multiselect[0].options == ["SBIN"]
