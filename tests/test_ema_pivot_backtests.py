"""Actual long/short trigger fills, staged exits, sizing and P&L conservation."""

from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from backtest.ema_pivot_engine import EmaPivotBacktestEngine
from backtest.portfolio_engine import SharedPortfolioEngine
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from services.technical_trading_service import TechnicalTradingService
from tests.test_ema_pivot_scanners import IDS, evaluate, signal_frame
from webapp.portfolio_backtesting import validate_result


def execution_frame(strategy_id, *, intraday=False):
    setup = EMA_PIVOT_SETUPS[strategy_id]
    # Build a bullish price path, then reflect all OHLC values for shorts.
    bullish_id = next(
        key
        for key, item in EMA_PIVOT_SETUPS.items()
        if item.fast == setup.fast and item.direction == 1
    )
    pair = signal_frame(bullish_id, mode="intraday" if intraday else "swing")
    frame = pd.concat(
        [pair, *[pair.iloc[-1:].copy() for _ in range(4)]], ignore_index=True
    )
    frame.index = pd.date_range(
        "2026-10-08 10:00" if intraday else "2026-10-07",
        periods=6,
        freq="15min" if intraday else "B",
        tz="Asia/Kolkata",
    )
    partial = 103.1 + setup.partial_r * setup.stop_atr
    final = 103.1 + setup.final_r * setup.stop_atr if setup.final_r else partial - 2.8
    frame.loc[frame.index[2], ["open", "high", "low", "close"]] = [
        103.1,
        104.0,
        102.5,
        103.4,
    ]
    frame.loc[frame.index[3], ["open", "high", "low", "close"]] = [
        partial - 0.8,
        partial + 0.5,
        partial - 1.1,
        partial + 0.2,
    ]
    frame.loc[frame.index[4], ["open", "high", "low", "close"]] = [
        partial + 0.1,
        max(final + 0.5, partial + 0.5),
        final - 0.5 if setup.trailing else partial - 0.2,
        final,
    ]
    frame.loc[frame.index[5], ["open", "high", "low", "close"]] = [
        final,
        final + 0.3,
        final - 0.3,
        final,
    ]
    if setup.direction == -1:
        for key in ("open", "close", f"EMA_{setup.fast}", f"EMA_{setup.slow}"):
            frame[key] = 200 - frame[key]
        frame["high"], frame["low"] = 200 - frame["low"], 200 - frame["high"]
        frame["RSI_WILDER_14"] = 100 - frame["RSI_WILDER_14"]
        for key in ("MACD", "MACD_SIGNAL", "MACD_HIST"):
            frame[key] = -frame[key]
        for period in ("DAY", "WEEK", "MONTH"):
            for level, value in {
                "P": 110,
                "R1": 120,
                "R2": 130,
                "S1": 60,
                "S2": 50,
            }.items():
                frame[f"TRAD_{period}_{level}"] = float(value)
    return frame


def run(strategy_id, frame=None, **kwargs):
    return SharedPortfolioEngine().run(
        {"TCS": execution_frame(strategy_id) if frame is None else frame},
        strategy_id=strategy_id,
        mode="swing",
        interval="1d",
        short_borrow_available=True,
        cost_bps=0,
        slippage_bps=0,
        **kwargs,
    )


@pytest.mark.parametrize("strategy_id", IDS)
def test_all_eight_fill_next_candle_and_take_half_then_exit_without_orders(strategy_id):
    result = run(strategy_id)
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["side"] == (
        "LONG" if EMA_PIVOT_SETUPS[strategy_id].direction == 1 else "SHORT"
    )
    assert trade["entry_at"] == execution_frame(strategy_id).index[2].isoformat()
    assert trade["entry_at"] > trade["entry_signal_at"]
    assert trade["planned_initial_risk"] <= 500
    assert trade["quantity"] >= 2
    legs = trade["exit_legs"]
    assert legs[0]["exit_reason"] == "PARTIAL_PROFIT"
    assert legs[0]["quantity"] == trade["quantity"] // 2
    assert sum(leg["quantity"] for leg in legs) == trade["quantity"]
    assert trade["net_pnl"] == pytest.approx(sum(leg["net_pnl"] for leg in legs))
    assert result["metrics"]["net_profit"] == pytest.approx(trade["net_pnl"])
    assert result["equity_curve"][-1]["cash"] == pytest.approx(
        100000 + trade["net_pnl"]
    )
    assert trade["exit_reason"] == (
        "PROTECTIVE_STOP" if EMA_PIVOT_SETUPS[strategy_id].trailing else "FINAL_TARGET"
    )


def test_missing_trigger_expires_in_one_bar_even_if_a_later_candle_breaks_out():
    key = IDS[0]
    frame = execution_frame(key)
    frame.loc[frame.index[2], ["open", "high", "low", "close"]] = [
        102,
        103,
        101.8,
        102.5,
    ]
    result = run(key, frame)
    assert result["trades"] == []
    assert result["rejection_counts"]["next_candle_trigger_expired"] == 1


@pytest.mark.parametrize("strategy_id", IDS[:2])
def test_gap_rechecks_pivot_room_using_actual_fill(strategy_id):
    frame = execution_frame(strategy_id)
    if EMA_PIVOT_SETUPS[strategy_id].direction == 1:
        frame["TRAD_WEEK_R1"] = 107
        frame.loc[frame.index[2], ["open", "high", "low", "close"]] = [
            106,
            107,
            105,
            106,
        ]
    else:
        frame["TRAD_WEEK_S1"] = 93
        frame.loc[frame.index[2], ["open", "high", "low", "close"]] = [94, 95, 93, 94]
    assert evaluate(strategy_id, frame.iloc[:2])["entry_state"] == "ARMED"
    result = run(strategy_id, frame)
    assert result["trades"] == []
    assert result["rejection_counts"]["gap_or_slippage_failed_pivot_room"] == 1


def test_partial_then_breakeven_is_conservative_when_ohlc_order_is_unknown():
    frame = execution_frame(IDS[0])
    frame.loc[frame.index[3], ["open", "high", "low", "close"]] = [104, 105, 102.5, 104]
    trade = run(IDS[0], frame)["trades"][0]
    assert trade["exit_reason"] == "BREAKEVEN_STOP_AMBIGUOUS_BAR"
    assert len(trade["exit_legs"]) == 2
    assert trade["exit_legs"][-1]["exit_price"] == trade["entry_price"]


def test_trailing_stop_is_next_candle_active_and_never_widens_with_atr():
    key = IDS[4]
    frame = execution_frame(key)
    frame.loc[frame.index[2], "ATR_WILDER_14"] = 0.1
    frame.loc[frame.index[3], ["open", "high", "low", "close", "ATR_WILDER_14"]] = [
        103.7,
        104.3,
        103.5,
        104,
        5,
    ]
    frame.loc[frame.index[4], ["open", "high", "low", "close", "ATR_WILDER_14"]] = [
        103.8,
        104,
        103,
        103.5,
        5,
    ]
    trade = run(key, frame)["trades"][0]
    assert trade["initial_stoploss"] == pytest.approx(101.1)
    assert trade["exit_at"] == frame.index[4].isoformat()
    assert trade["final_exit_price"] == pytest.approx(103.1)
    assert trade["exit_reason"] == "PROTECTIVE_STOP"


@pytest.mark.parametrize("strategy_id", IDS)
def test_completed_indicator_exit_executes_at_next_open(strategy_id):
    setup = EMA_PIVOT_SETUPS[strategy_id]
    frame = execution_frame(strategy_id)
    for offset in (2, 3, 4, 5):
        values = [103.1, 104, 102.5, 103.4]
        if setup.direction == -1:
            values = [
                200 - values[0],
                200 - values[2],
                200 - values[1],
                200 - values[3],
            ]
        frame.loc[frame.index[offset], ["open", "high", "low", "close"]] = values
    # The entry candle closes on the opposite side of the fast EMA; its
    # protective bracket remains untouched, so only the next open can exit.
    frame.loc[frame.index[2], f"EMA_{setup.fast}"] = 105 if setup.direction == 1 else 95
    result = run(strategy_id, frame)
    trade = result["trades"][0]
    assert trade["exit_at"] == frame.index[3].isoformat()
    assert trade["exit_reason"] == "STRATEGY_EXIT"


def test_active_stop_has_priority_over_partial_target_and_gap_can_exceed_planned_risk():
    frame = execution_frame(IDS[0])
    frame.loc[frame.index[3], ["open", "high", "low", "close"]] = [95, 108, 94, 100]
    trade = run(IDS[0], frame)["trades"][0]
    assert len(trade["exit_legs"]) == 1
    assert trade["exit_reason"] == "PROTECTIVE_STOP"
    assert trade["exit_price"] == 95
    assert trade["net_pnl"] < -trade["planned_initial_risk"]


def test_three_stock_shared_capital_scores_fees_slippage_and_fill_pnl_reconcile():
    key = IDS[0]
    result = SharedPortfolioEngine().run(
        {symbol: execution_frame(key) for symbol in ("A", "B", "C", "D")},
        strategy_id=key,
        mode="swing",
        interval="1d",
        cost_bps=12,
        slippage_bps=5,
    )
    assert {trade["symbol"] for trade in result["trades"]} == {"A", "B", "C"}
    assert result["metrics"]["max_observed_positions"] == 3
    assert result["metrics"]["max_capital_committed"] <= 80000
    assert result["metrics"]["minimum_cash"] >= 20000
    assert all(
        a["allocation_budget"] == pytest.approx(80000 / 3)
        for a in result["allocations"]
    )
    assert all(a["planned_initial_risk"] <= 500 for a in result["allocations"])
    assert sum(t["net_pnl"] for t in result["trades"]) == pytest.approx(
        result["metrics"]["net_profit"]
    )
    assert sum(f["transaction_costs"] for f in result["exit_fills"]) == pytest.approx(
        result["metrics"]["transaction_costs"]
    )
    assert sum(f["net_pnl"] for f in result["exit_fills"]) == pytest.approx(
        result["metrics"]["net_profit"]
    )
    assert (
        result["metrics"]["transaction_costs"] > 0
        and result["metrics"]["slippage_impact_estimate"] > 0
    )
    validate_result(
        {
            "status": "completed",
            **result,
            "parameters": {
                "deployment_limit": 80000,
                "cash_reserve": 20000,
                "max_positions": 3,
                "reserve_policy": "entry_budget_floor_losses_can_reduce_cash",
            },
        }
    )


def test_short_borrow_is_an_explicit_assumption():
    with pytest.raises(ValueError, match="available-borrow"):
        EmaPivotBacktestEngine().run(
            {"TCS": execution_frame(IDS[1])},
            strategy_id=IDS[1],
            mode="swing",
            interval="1d",
        )


def test_intraday_trigger_cannot_cross_session_and_positions_square_off_at_1500():
    key = IDS[0]
    frame = execution_frame(key, intraday=True)
    frame.index = pd.DatetimeIndex(
        [
            "2026-10-08 14:00",
            "2026-10-08 14:15",
            "2026-10-08 14:30",
            "2026-10-08 14:45",
            "2026-10-08 15:00",
            "2026-10-08 15:15",
        ],
        tz="Asia/Kolkata",
    )
    frame.loc[frame.index[3], ["open", "high", "low", "close"]] = [
        103.5,
        104,
        103,
        103.4,
    ]
    result = SharedPortfolioEngine().run(
        {"TCS": frame},
        strategy_id=key,
        mode="intraday",
        interval="15m",
        cost_bps=0,
        slippage_bps=0,
    )
    assert result["trades"][0]["exit_reason"] == "INTRADAY_SESSION_EXIT_1500"
    assert pd.Timestamp(result["trades"][0]["exit_at"]).hour == 15
    frame = frame.drop(frame.index[4])
    with pytest.raises(ValueError, match="square-off"):
        SharedPortfolioEngine().run(
            {"TCS": frame},
            strategy_id=key,
            mode="intraday",
            interval="15m",
            cost_bps=0,
            slippage_bps=0,
        )


def test_admin_api_exposes_all_eight_and_validates_research_inputs(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "ema-pivot-test-admin-" * 3)
    client = TestClient(
        create_app(SimpleNamespace(technical_trading_service=lambda: None))
    )
    catalog = client.get("/technical/strategies").json()
    assert set(IDS) <= {row["strategy_id"] for row in catalog["strategies"]}
    for field, value in [
        ("tick_size", 0),
        ("liquidity_confirmation", "yes"),
        ("short_borrow_available", 1),
    ]:
        response = client.post(
            "/technical/portfolio-backtest",
            json={"symbols": ["TCS"], "strategy_id": IDS[0], field: value},
            headers={"X-TrendForge-Admin-Key": "ema-pivot-test-admin-" * 3},
        )
        assert response.status_code == 422


def test_actual_technical_scanner_returns_research_plans_without_paper_candidates():
    frame = pd.concat(
        [signal_frame(IDS[0]).iloc[:1]] * 65 + [signal_frame(IDS[0]).iloc[-1:]],
        ignore_index=True,
    )
    frame.index = pd.bdate_range("2026-01-05", periods=len(frame), tz="Asia/Kolkata")
    calls = []
    service = TechnicalTradingService(
        market_data=SimpleNamespace(
            batch_candles_with_errors=lambda *a, **k: ({"TCS": frame}, {})
        ),
        repository=SimpleNamespace(),
        indicator_engine=SimpleNamespace(calculate=lambda f: f),
        paper_auto_entry=SimpleNamespace(
            process_scan=lambda *a, **k: calls.append((a, k)) or {"opened": []}
        ),
    )
    result = service.scan(
        symbols=["TCS"],
        mode="swing",
        strategy_id=IDS[0],
        now=pd.Timestamp("2026-10-08 16:00", tz="Asia/Kolkata").to_pydatetime(),
    )
    assert result["armed_setups"] == 1
    assert result["results"][0]["entry_plan"]["valid_for_next_candle_only"] is True
    assert result["results"][0]["execution_eligible"] is False
    assert result["top_picks"] == []
    assert calls[0][0][0]["execution_top_picks"] == []
    assert calls[0][1]["execute_requested"] is False
