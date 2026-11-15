"""Causal annual references, completed daily triggers and reconciled fills."""

import numpy as np
import pandas as pd
import pytest

from backtest.vwma_yearly_engine import VwmaYearlyBacktestEngine
from core.database import initialize_database
from database.repositories.backtest_results import BacktestResultsRepository
from scanner.strategy_horizons import horizon_strategy, scanner_horizon_choices
from scanner.strategy_registry import get_strategy
from scanner.vwma_yearly import STRATEGY_ID, add_indicators, entry_plan, evaluate
from services.execution_report import validate_result
from services.portfolio_backtest_service import PortfolioBacktestService
from services.technical_trading_service import TechnicalTradingService

NOW = pd.Timestamp("2026-11-15T17:00:00+05:30")


def history():
    index = pd.bdate_range("2022-01-03", "2026-11-13", tz="Asia/Kolkata")
    x = np.arange(len(index))
    close = 100 + x * 0.04 + 1.5 * np.sin(x / 2) + 2 * np.sin(x / 15)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.5,
            "close": close,
            "volume": np.where(x % 7 == 0, 4000.0, 1000.0),
        },
        index=index,
    )


def execution_frame():
    index = pd.bdate_range("2026-03-02", periods=6, tz="Asia/Kolkata")
    frame = pd.DataFrame(
        {
            "open": [98, 100, 103, 110, 123, 125],
            "high": [99, 102, 104, 120, 129, 126],
            "low": [97, 99, 100, 105, 102, 124],
            "close": [98, 101, 103, 118, 125, 125],
            "volume": 2000.0,
            "VWMA_20": [90, 92, 93, 94, 95, 96],
            "VWMA_50": [85, 86, 87, 88, 89, 90],
            "RSI_WILDER_14": 60.0,
            "VOL_SMA_20": 1100.0,
            "HIGH_20_PREV": 100.0,
            "LOW_5": 95.0,
        },
        index=index,
    )
    for name, value in {
        "P": 70,
        "R1": 80,
        "R2": 90,
        "R3": 100,
        "S1": 60,
        "S2": 50,
        "S3": 40,
    }.items():
        frame["FIB_YEAR_" + name] = float(value)
    return frame.astype(float)


def simulate(frame):
    return VwmaYearlyBacktestEngine().run(
        {"EXAMPLE": frame},
        strategy_id=STRATEGY_ID,
        mode="swing",
        interval="1d",
        cost_bps=12,
        slippage_bps=0,
    )


def test_fibonacci_formulas_warmup_and_future_invariance():
    raw = history()
    out = add_indicators(raw)
    previous = raw.loc["2025"]
    p = (previous.high.max() + previous.low.min() + previous.close.iloc[-1]) / 3
    span = previous.high.max() - previous.low.min()
    row = out.loc["2026"].iloc[0]
    assert pytest.approx(p) == row.FIB_YEAR_P
    assert pytest.approx(p + 0.382 * span) == row.FIB_YEAR_R1
    assert pytest.approx(p + 0.618 * span) == row.FIB_YEAR_R2
    assert pytest.approx(p + span) == row.FIB_YEAR_R3
    assert pytest.approx(p - span) == row.FIB_YEAR_S3
    assert out.loc["2023", "FIB_YEAR_P"].isna().all()
    prefix = add_indicators(raw.loc[:"2026-04-30"])
    pd.testing.assert_frame_equal(prefix, out.loc[prefix.index])
    missing = add_indicators(raw.loc[raw.index.year != 2025])
    assert missing.loc["2026", "FIB_YEAR_P"].isna().all()


def test_vwma_and_volume_include_signal_and_high_excludes_it():
    raw = history()
    out = add_indicators(raw)
    last20 = raw.iloc[-20:]
    assert (
        pytest.approx((last20.close * last20.volume).sum() / last20.volume.sum())
        == out.iloc[-1].VWMA_20
    )
    assert last20.volume.mean() == out.iloc[-1].VOL_SMA_20
    assert raw.high.iloc[-21:-1].max() == out.iloc[-1].HIGH_20_PREV


@pytest.mark.parametrize(
    "field,value",
    [
        ("RSI_WILDER_14", 54.9),
        ("RSI_WILDER_14", 75.1),
        ("volume", 1600),
        ("VWMA_20", 80),
        ("FIB_YEAR_P", np.nan),
    ],
)
def test_each_failed_confirmation_blocks_entry(field, value):
    frame = execution_frame()
    current = frame.iloc[1].copy()
    assert evaluate(frame.iloc[0], current)["entry_state"] == "ARMED"
    current[field] = value
    assert evaluate(frame.iloc[0], current)["entry_state"] == "WAIT"


def test_annual_reset_is_not_a_price_breakout():
    frame = execution_frame()
    previous, current = frame.iloc[0].copy(), frame.iloc[1].copy()
    previous.name = pd.Timestamp("2025-12-31", tz="Asia/Kolkata")
    current.name = pd.Timestamp("2026-01-02", tz="Asia/Kolkata")
    current.HIGH_20_PREV = 200
    signal = evaluate(previous, current)
    assert signal["crossed_pivots"] == []
    assert signal["entry_state"] == "WAIT"


def test_next_session_gap_partial_final_and_risk_reconcile():
    frame = execution_frame()
    result = simulate(frame)
    trade = result["trades"][0]
    assert trade["entry_at"] == frame.index[2].isoformat()
    assert trade["entry_price"] == 103
    assert trade["initial_stoploss"] == pytest.approx(94.7)
    assert [leg["exit_reason"] for leg in result["exit_fills"]] == [
        "PARTIAL_PROFIT",
        "FINAL_TARGET",
    ]
    assert trade["stoploss"] == trade["initial_stoploss"]
    assert trade["planned_initial_risk"] <= trade["risk_budget"]
    validate_result(
        {
            "status": "completed",
            **result,
            "parameters": {
                "deployment_limit": 100000.0,
                "cash_reserve": 0.0,
                "max_positions": 3,
            },
        }
    )


def test_stop_wins_same_bar_ambiguity_and_trigger_expires():
    frame = execution_frame()
    frame.iloc[2, frame.columns.get_loc("low")] = 90
    frame.iloc[2, frame.columns.get_loc("high")] = 150
    assert simulate(frame)["trades"][0]["exit_reason"] == "PROTECTIVE_STOP"
    frame = execution_frame()
    frame.loc[frame.index[2], ["open", "high", "low", "close"]] = [101, 102.2, 100, 101]
    result = simulate(frame)
    assert result["trades"] == []
    assert result["rejection_counts"]["next_candle_trigger_expired"] == 1


def test_close_below_vwma_exits_next_open():
    frame = execution_frame()
    frame.loc[frame.index[3], ["open", "high", "low", "close", "VWMA_20"]] = [
        110,
        115,
        106,
        108,
        109,
    ]
    frame.loc[frame.index[4], "open"] = 107
    trade = simulate(frame)["trades"][0]
    assert trade["exit_reason"] == "STRATEGY_EXIT"
    assert trade["exit_at"] == frame.index[4].isoformat()
    assert trade["exit_price"] == 107


def test_entry_plan_rounding_and_actual_fill_reanchor():
    row = execution_frame().iloc[1]
    plan = entry_plan(row)
    assert plan["entry_trigger"] == pytest.approx(102.35)
    actual = entry_plan(row, entry=104)
    assert actual["stoploss"] == plan["stoploss"]
    assert actual["target2"] == pytest.approx(104 + 3 * (104 - plan["stoploss"]))


def test_service_scan_backtest_persistence_and_research_catalog(tmp_path):
    class Market:
        calls = []

        def batch_candles_with_errors(self, symbols, **kwargs):
            self.calls.append(kwargs)
            return {symbol: history() for symbol in symbols}, {}

    path = str(tmp_path / "vwma.db")
    initialize_database(path)
    service = TechnicalTradingService(
        market_data=Market(), repository=BacktestResultsRepository(db_path=path)
    )
    try:
        result = PortfolioBacktestService(service).run(
            symbols=["MCX"], mode="swing", strategy_id=STRATEGY_ID, period="2y", now=NOW
        )
        validate_result(result)
        assert result["metrics"]["total_trades"] > 0
        assert result["parameters"]["pivot_type"] == "Fibonacci"
        assert result["report"]["xlsx_base64"]
        assert (
            service.repository.by_run_id(result["run_id"])["result"]["report"]
            == result["report"]
        )
        assert service.market_data.calls == [{"period": "5y", "interval": "1d"}]
        scan = service.scan(
            symbols=["MCX"], mode="swing", strategy_id=STRATEGY_ID, period="2y", now=NOW
        )
        assert scan["results"][0]["signal"] != "ERROR"
        assert scan["results"][0]["execution_eligible"] is False
        assert horizon_strategy("short_term", STRATEGY_ID)["interval"] == "1d"
        assert STRATEGY_ID in {
            r["strategy_id"] for r in scanner_horizon_choices("short_term").values()
        }
        assert get_strategy(STRATEGY_ID)["paper_eligible"] is False
        with pytest.raises(ValueError):
            service.scan(
                symbols=["MCX"],
                mode="swing",
                strategy_id=STRATEGY_ID,
                execute_paper=True,
                now=NOW,
            )
    finally:
        service.repository.close()
