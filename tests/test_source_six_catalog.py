"""Exactly six active source strategies; historical lineage grants exit access only."""

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from api.app import create_app
from scanner.multi_strategy_engine import MultiStrategyEngine
from scanner.strategy_registry import get_strategy, list_strategies
from scanner.workspace_strategies import strategy_choices
from services.technical_trading_service import TechnicalTradingService

EXPECTED = {
    "tf_intraday_ema9_20_momentum",
    "tf_intraday_vwma9_26_rsi_volume",
    "tf_swing_ema20_50_rsi_volume",
    "tf_swing_vwma9_26_rsi_volume",
    "tf_medium_ema50_100",
    "tf_long_ema100_200",
}
RETIRED = {
    "tf_intraday_ema20_50_rsi_volume",
    "tf_intraday_supertrend_vwap_pivots",
    "tf_swing_macd_trend",
    "tf_golden_cross_50_200",
    "tf_rsi_momentum_confirmation",
    "tf_rsi_mean_reversion",
    "tpl_supertrend_rsi",
    "tpl_ema_adx_trend",
    "tpl_vwap_volume_breakout",
    "tpl_macd_trend_confirmation",
    "tpl_bollinger_breakout",
    "tpl_volume_breakout",
    "tpl_52week_high_momentum",
}


def test_catalog_and_every_workspace_selector_expose_only_the_source_six():
    assert {row["strategy_id"] for row in list_strategies()} == EXPECTED
    choices = [strategy_choices(mode) for mode in ["intraday", "swing", "positional"]]
    assert all(len(choice) == 2 for choice in choices)
    assert {value for choice in choices for value in choice.values()} == EXPECTED
    assert list_strategies(source="template") == []
    health = MultiStrategyEngine().readiness()
    assert set(health["executable_strategy_ids"]) == EXPECTED - {
        "tf_medium_ema50_100",
        "tf_long_ema100_200",
    }
    assert set(health["review_required_strategy_ids"]) == {
        "tf_medium_ema50_100",
        "tf_long_ema100_200",
    }
    for strategy_id in health["review_required_strategy_ids"]:
        assert get_strategy(strategy_id)["paper_eligible"] is False
        assert get_strategy(strategy_id)["implementation_status"] == "review_required"


@pytest.mark.parametrize("strategy_id", sorted(RETIRED))
def test_retired_strategies_are_not_reintroduced_through_detail_or_scan_api(
    strategy_id,
):
    factory = SimpleNamespace(
        technical_trading_service=lambda: TechnicalTradingService(
            market_data=object(),
            repository=SimpleNamespace(),
        )
    )
    client = TestClient(create_app(factory))
    assert client.get("/technical/strategies/" + strategy_id).status_code == 404
    for path, stock in [
        ("scan", {"symbols": ["TCS"]}),
        ("backtest", {"symbol": "TCS"}),
    ]:
        response = client.post(
            "/technical/" + path,
            json={
                **stock,
                "mode": "swing",
                "strategy_id": strategy_id,
            },
        )
        assert response.status_code == 422


def test_omitted_strategy_routes_to_an_active_source_pair_instead_of_legacy_momentum():
    class Service:
        def scan(self, **kwargs):
            return kwargs

        backtest = scan

    client = TestClient(
        create_app(SimpleNamespace(technical_trading_service=lambda: Service()))
    )
    assert (
        client.post("/technical/scan", json={"symbols": ["TCS"]}).json()["strategy_id"]
        == "tf_intraday_ema9_20_momentum"
    )
    assert (
        client.post("/technical/backtest", json={"symbol": "TCS"}).json()["strategy_id"]
        == "tf_swing_ema20_50_rsi_volume"
    )


def test_retired_lineage_can_exit_but_never_returns_a_buy_for_new_entry():
    frame = pd.DataFrame(
        {
            "close": [100.0, 100.0],
            "SUPERTREND_DIR": [1.0, -1.0],
            "RSI_14": [65.0, 30.0],
            "ATR": [2.0, 2.0],
        },
        index=pd.date_range("2026-10-20", periods=2, tz="Asia/Kolkata"),
    )
    engine = MultiStrategyEngine()
    with pytest.raises(ValueError):
        engine.evaluate(
            frame, mode="swing", interval="1d", strategy_ids=["tpl_supertrend_rsi"]
        )
    result = engine.evaluate_exit(
        frame, mode="swing", interval="1d", strategy_ids=["tpl_supertrend_rsi"]
    )
    row = result["evaluations"][0]
    assert row["signal"] == "EXIT"
    assert row["exit_only"] is True
    assert row["paper_eligible"] is False
    frame["SUPERTREND_DIR"] = 1.0
    frame["RSI_14"] = 65.0
    row = engine.evaluate_exit(
        frame, mode="swing", interval="1d", strategy_ids=["tpl_supertrend_rsi"]
    )["evaluations"][0]
    assert row["signal"] == "HOLD"


def test_positional_source_choices_are_visible_with_no_guessed_scores_or_execution(
    monkeypatch,
):
    calls = []

    class Client:
        def get_json(self, path, **kwargs):
            return {"rows": [{"symbol": "TCS", "sector": "IT"}]}

        def post_json(self, *args, **kwargs):
            calls.append(args)
            raise AssertionError("Review-only strategy must never run")

    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: Client())
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "webapp/pages/kite_backtesting.py"
    ).run(timeout=15)
    app.radio[0].set_value("positional").run(timeout=15)
    assert not app.exception
    assert (
        len(next(w for w in app.selectbox if w.label == "Scanner / strategy").options)
        == 2
    )
    assert next(w for w in app.button if w.label == "Run Kite backtest").disabled
    assert next(w for w in app.button if w.label == "Run technical scan").disabled
    assert any("Review required" in w.value for w in app.warning)
    assert app.dataframe[0].value.iloc[0]["score"] is None
    assert calls == []
