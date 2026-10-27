"""Shared capital, execution chronology and real source-rule portfolio coverage."""

from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.portfolio_backtest_router import portfolio_backtest_router
from backtest.portfolio_engine import SharedPortfolioEngine
from scanner.portfolio_policy import allocate_candidates, evidence_rows
from services.portfolio_backtest_service import PortfolioBacktestService
from services.technical_trading_service import (
    TechnicalTradingService,
    TechnicalTradingValidationError,
)

STRATEGY = "tf_swing_ema20_50_rsi_volume"


class Decisions:
    def readiness(self):
        return {"executable_strategy_ids": [STRATEGY, "tf_intraday_ema9_20_momentum"]}

    def evaluate(self, frame, **kwargs):
        row = frame.iloc[-1]
        return {
            "evaluations": [
                {
                    "status": "evaluated",
                    "signal": row["directive"],
                    "score": row["test_score"],
                    "risk": {
                        "entry": float(row["close"]),
                        "stoploss": float(row["close"]) - 4,
                        "target2": float(row["close"]) + 8,
                        "reward_risk": 2,
                    },
                    "checks": {"synthetic_fixture": True},
                }
            ]
        }


def frame(score=100, periods=8, intraday=False):
    index = (
        pd.date_range("2026-01-05 09:30", periods=24, freq="15min", tz="Asia/Kolkata")
        if intraday
        else pd.bdate_range("2026-01-05", periods=periods, tz="Asia/Kolkata")
    )
    result = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 2000.0,
            "RSI_14": 65.0,
            "ATR": 2.0,
            "directive": "HOLD",
            "test_score": float(score),
        },
        index=index,
    )
    result.iloc[1, result.columns.get_loc("directive")] = "BUY"
    return result


def simulate(frames, **kwargs):
    return SharedPortfolioEngine(strategy_engine=Decisions()).run(
        frames,
        strategy_id=STRATEGY,
        mode="swing",
        interval="1d",
        **kwargs,
    )


def test_shared_cash_only_top_three_and_proportional_whole_share_allocations():
    result = simulate(
        {s: frame(score) for s, score in zip("ABCD", [90, 60, 30, 10], strict=True)}
    )
    assert [t["symbol"] for t in result["trades"]] == ["A", "B", "C"]
    assert [a["allocation_budget"] for a in result["allocations"]] == pytest.approx(
        [40000, 80000 / 3, 80000 / 6]
    )
    assert result["metrics"]["max_observed_positions"] == 3
    assert result["metrics"]["max_capital_committed"] <= 80000
    assert result["metrics"]["minimum_cash"] >= 20000
    assert result["metrics"]["initial_capital"] == 100000
    assert all(
        type(t["quantity"]) is int and t["quantity"] > 0 for t in result["trades"]
    )
    for t in result["trades"]:
        assert pd.Timestamp(t["entry_at"]) > pd.Timestamp(t["entry_signal_at"])
        assert t["capital_committed"] <= t["allocation_budget"]
        assert t["risk_reward"] == "1:2.00"
        assert t["indicators"]["RSI_14"] == 65
    assert sum(t["net_pnl"] for t in result["trades"]) == pytest.approx(
        result["metrics"]["net_profit"], abs=0.04
    )


def test_equal_scores_split_equally_and_hold_or_invalid_brackets_never_trade():
    rows = [
        {
            "symbol": s,
            "score": 100,
            "signal": "BUY",
            "entry": 100,
            "stoploss": 95,
            "target2": 110,
        }
        for s in "ABC"
    ]
    rows += [
        {**rows[0], "symbol": "HOLD", "signal": "HOLD"},
        {**rows[0], "symbol": "BAD", "stoploss": 101},
    ]
    allocated = allocate_candidates(rows, budget=80000, slots=3)
    assert [r["symbol"] for r in allocated] == list("ABC")
    assert [r["allocation_budget"] for r in allocated] == pytest.approx([80000 / 3] * 3)
    held = frame()
    held["directive"] = "HOLD"
    result = simulate({"A": held})
    assert result["trades"] == [] and result["metrics"]["final_capital"] == 100000


def test_intrabar_exit_proceeds_do_not_fund_same_bar_open_entries():
    frames = {s: frame() for s in "ABCD"}
    frames["D"]["directive"] = "HOLD"
    frames["D"].iloc[2, frames["D"].columns.get_loc("directive")] = "BUY"
    for s in "ABC":
        frames[s].iloc[3, frames[s].columns.get_loc("low")] = 80
    result = simulate(frames)
    assert "D" not in [r["symbol"] for r in result["allocations"]]


def test_known_next_open_exit_frees_one_slot_and_cash_without_exceeding_three():
    frames = {s: frame() for s in "ABCD"}
    frames["D"]["directive"] = "HOLD"
    frames["A"].iloc[2, frames["A"].columns.get_loc("directive")] = "EXIT"
    frames["D"].iloc[2, frames["D"].columns.get_loc("directive")] = "BUY"
    result = simulate(frames)
    assert [r["symbol"] for r in result["allocations"]] == list("ABCD")
    assert result["metrics"]["max_observed_positions"] == 3
    assert result["metrics"]["minimum_cash"] >= 20000


def test_both_brackets_hit_stop_first_and_no_negative_cash():
    stock = frame()
    stock.iloc[2, stock.columns.get_loc("low")] = 80
    stock.iloc[2, stock.columns.get_loc("high")] = 120
    result = simulate({"A": stock})
    assert result["trades"][0]["exit_reason"] == "ATR_STOP"
    assert result["trades"][0]["net_pnl"] < 0
    assert result["metrics"]["max_observed_positions"] == 1
    assert result["metrics"]["minimum_cash"] >= 20000


def test_future_prices_and_scores_do_not_change_earlier_allocations():
    frames = {
        s: frame(score) for s, score in zip("ABCD", [90, 80, 70, 20], strict=True)
    }
    before = simulate(frames)
    frames["D"].iloc[5:, frames["D"].columns.get_loc("test_score")] = 100
    frames["D"].iloc[5:, frames["D"].columns.get_loc("close")] = 1000
    frames["D"].iloc[5:, frames["D"].columns.get_loc("high")] = 1001
    after = simulate(frames)
    assert after["allocations"] == before["allocations"]


def test_profit_does_not_increase_fixed_80000_cap():
    stock = frame()
    stock.iloc[2, stock.columns.get_loc("high")] = 120
    stock.iloc[3, stock.columns.get_loc("directive")] = "BUY"
    result = simulate({"A": stock})
    assert len(result["allocations"]) == 2
    assert result["allocations"][1]["allocation_budget"] == 80000
    assert result["metrics"]["max_capital_committed"] <= 80000


def test_high_price_does_not_borrow_or_consume_reserve():
    stock = frame()
    stock[["open", "close", "high", "low"]] *= 1000
    result = simulate({"A": stock})
    assert not result["trades"]
    assert result["metrics"]["final_capital"] == 100000


@pytest.mark.parametrize("damage", ["unaligned", "duplicate", "nonfinite", "bad_ohlc"])
def test_incomplete_or_corrupt_history_cannot_generate_fabricated_portfolio(damage):
    a, b = frame(), frame()
    if damage == "unaligned":
        b = b.drop(b.index[3])
    elif damage == "duplicate":
        b.index = [b.index[0]] * len(b)
    elif damage == "nonfinite":
        b.iloc[2, b.columns.get_loc("open")] = float("nan")
    else:
        b.iloc[2, b.columns.get_loc("high")] = 50
    with pytest.raises(ValueError):
        simulate({"A": a, "B": b})


def test_intraday_exit_and_missing_squareoff_candle():
    stock = frame(intraday=True)
    engine = SharedPortfolioEngine(strategy_engine=Decisions())
    args = {
        "strategy_id": "tf_intraday_ema9_20_momentum",
        "mode": "intraday",
        "interval": "15m",
    }
    result = engine.run({"A": stock}, **args)
    assert pd.Timestamp(result["trades"][0]["exit_at"]).strftime("%H:%M") == "15:00"
    with pytest.raises(ValueError, match="square-off"):
        engine.run({"A": stock.drop(stock.index[22])}, **args)
    stock["directive"] = "HOLD"
    stock.iloc[20, stock.columns.get_loc("directive")] = "BUY"
    assert engine.run({"A": stock}, **args)["trades"] == []


def canonical_frame():
    result = frame(periods=75)
    result["EMA_20"] = 95.0
    result.loc[result.index[60] :, "EMA_20"] = 101.0
    result["EMA_50"] = 100.0
    result["VOL_SMA_20"] = 1000.0
    result["close"] = 101.0
    result["high"] = 102.0
    result["low"] = 99.0
    return result


class Repository:
    def __init__(self):
        self.rows = {}

    def by_run_id(self, run_id):
        return self.rows.get(run_id)

    def save(self, row):
        self.rows[row["run_id"]] = row


def service():
    data = canonical_frame()
    market = SimpleNamespace(
        batch_candles_with_errors=lambda symbols, **kwargs: (
            {s: data.copy() for s in symbols},
            {},
        )
    )
    return TechnicalTradingService(
        market_data=market,
        repository=Repository(),
        indicator_engine=SimpleNamespace(calculate=lambda f: f),
    )


def test_real_canonical_rules_recomputed_and_result_saved_as_one_portfolio():
    technical = service()
    result = PortfolioBacktestService(technical).run(
        symbols=list("ABCD"),
        mode="swing",
        strategy_id=STRATEGY,
        period="2y",
        run_id="shared-test",
    )
    assert result["metrics"]["max_observed_positions"] == 3
    assert result["safety"]["paper_orders_created"] is False
    assert technical.repository.rows["shared-test"]["result"] == result
    assert len(result["trades"]) == 3
    assert all(
        t["indicators"]["EMA_20"] == 101 and t["risk_reward"] == "1:2.00"
        for t in result["trades"]
    )
    from webapp.portfolio_backtesting import validate_result

    validate_result(result)


def test_no_partial_universe_or_review_strategy_is_silently_simulated():
    technical = service()
    technical.market_data.batch_candles_with_errors = lambda *a, **k: ({}, {})
    with pytest.raises(TechnicalTradingValidationError, match="incomplete"):
        PortfolioBacktestService(technical).run(
            symbols=["TCS"], mode="swing", strategy_id=STRATEGY
        )
    with pytest.raises(TechnicalTradingValidationError, match="executable"):
        PortfolioBacktestService(technical).run(
            symbols=["TCS"], mode="swing", strategy_id="tf_medium_ema50_100"
        )
    assert not technical.repository.rows


def test_api_requires_admin_and_cannot_override_account_policy(monkeypatch):
    technical = service()
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "portfolio-test-admin-" * 3)
    app = FastAPI()
    app.include_router(portfolio_backtest_router(lambda: technical))
    client = TestClient(app)
    payload = {
        "symbols": ["A", "B", "C", "D"],
        "strategy_id": STRATEGY,
        "mode": "swing",
    }
    assert client.post("/technical/portfolio-backtest", json=payload).status_code == 401
    headers = {"X-TrendForge-Admin-Key": "portfolio-test-admin-" * 3}
    for field, value in [
        ("capital", 200000),
        ("max_positions", 5),
        ("execute_paper", True),
    ]:
        assert (
            client.post(
                "/technical/portfolio-backtest",
                json={**payload, field: value},
                headers=headers,
            ).status_code
            == 422
        )
    response = client.post(
        "/technical/portfolio-backtest", json=payload, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["parameters"]["cash_reserve"] == 20000


def test_indicator_values_and_risk_ratio_are_derived_not_fabricated():
    rows = evidence_rows(
        [
            {
                "symbol": "A",
                "signal": "HOLD",
                "entry": 100,
                "stoploss": 95,
                "target2": 110,
                "indicators": {"RSI_14": 65, "ATR": float("nan")},
            }
        ]
    )
    assert rows[0]["risk_reward"] == "1:2.00"
    assert rows[0]["indicator_RSI_14"] == 65
    assert rows[0]["indicator_ATR"] is None


@pytest.mark.parametrize(
    "damage", ["over_budget", "missing_trade_time", "missing_equity"]
)
def test_inconsistent_financial_ui_response_is_rejected(damage):
    from webapp.api_client import ApiError
    from webapp.portfolio_backtesting import validate_result

    result = PortfolioBacktestService(service()).run(
        symbols=["A"],
        strategy_id=STRATEGY,
        mode="swing",
    )
    if damage == "over_budget":
        result["equity_curve"][2]["capital_committed"] = 80001
    elif damage == "missing_trade_time":
        result["trades"][0].pop("exit_at")
    else:
        result["equity_curve"][0].pop("equity")
    with pytest.raises(ApiError):
        validate_result(result)
