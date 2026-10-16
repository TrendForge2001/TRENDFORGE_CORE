from __future__ import annotations

import pandas as pd
import pytest

from backtest.backtest_engine import BacktestConfig, BacktestEngine


def frame() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 109.0, 110.0],
            "close": [100.0, 101.0, 103.0, 109.0, 108.0],
            "entry": [False, True, False, False, False],
            "exit": [False, False, False, True, False],
        },
        index=dates,
    )


def entry_rule(previous, current):
    del previous
    if bool(current.get("entry")):
        return {"source": "unit"}
    return None


def exit_rule(previous, current):
    del previous
    if bool(current.get("exit")):
        return {"reason": "UNIT_EXIT"}
    return None


def test_engine_uses_next_bar_open_without_same_close_lookahead():
    result = BacktestEngine(
        BacktestConfig(initial_capital=100_000)
    ).run(
        frame(),
        entry_rule=entry_rule,
        exit_rule=exit_rule,
    )

    assert result.metrics["total_trades"] == 1
    trade = result.trades[0]

    assert trade["entry_signal_at"].startswith("2026-01-02")
    assert trade["entry_at"].startswith("2026-01-03")
    assert trade["entry_raw_open"] == 102.0
    assert trade["quantity"] == 980

    assert trade["exit_signal_at"].startswith("2026-01-04")
    assert trade["exit_at"].startswith("2026-01-05")
    assert trade["exit_raw_open"] == 110.0
    assert trade["exit_reason"] == "UNIT_EXIT"
    assert trade["net_pnl"] == 7840.0
    assert result.metrics["final_capital"] == 107840.0


def test_engine_costs_and_slippage_reduce_result():
    free = BacktestEngine(
        BacktestConfig(initial_capital=100_000)
    ).run(
        frame(),
        entry_rule=entry_rule,
        exit_rule=exit_rule,
    )
    friction = BacktestEngine(
        BacktestConfig(
            initial_capital=100_000,
            cost_bps=10,
            slippage_bps=10,
        )
    ).run(
        frame(),
        entry_rule=entry_rule,
        exit_rule=exit_rule,
    )

    assert friction.metrics["net_profit"] < free.metrics["net_profit"]
    assert friction.metrics["transaction_costs"] > 0
    assert friction.metrics["slippage_impact_estimate"] > 0


def test_engine_forces_open_position_closed_at_final_close():
    data = frame().copy()
    data["exit"] = False

    result = BacktestEngine(
        BacktestConfig(initial_capital=100_000)
    ).run(
        data,
        entry_rule=entry_rule,
        exit_rule=exit_rule,
    )

    assert result.metrics["total_trades"] == 1
    trade = result.trades[0]
    assert trade["exit_reason"] == "END_OF_TEST"
    assert trade["exit_at"].startswith("2026-01-05")
    assert trade["exit_price"] == 108.0


def test_engine_can_leave_final_position_marked_to_market_when_configured():
    data = frame().copy()
    data["exit"] = False

    result = BacktestEngine(
        BacktestConfig(
            initial_capital=100_000,
            force_final_exit=False,
        )
    ).run(
        data,
        entry_rule=entry_rule,
        exit_rule=exit_rule,
    )

    assert result.trades == []
    assert result.metrics["final_capital"] == result.equity_curve[-1]["equity"]
    assert result.metrics["final_capital"] > 100_000
    assert result.equity_curve[-1]["market_value"] > 0


def test_engine_rejects_invalid_frames_and_signal_contracts():
    engine = BacktestEngine()

    with pytest.raises(ValueError, match="missing required columns"):
        engine.run(
            pd.DataFrame({"close": [1.0, 2.0]}),
            entry_rule=entry_rule,
            exit_rule=exit_rule,
        )

    bad = frame()

    def invalid_rule(previous, current):
        del previous, current
        return True

    with pytest.raises(TypeError, match="mapping or None"):
        engine.run(
            bad,
            entry_rule=invalid_rule,
            exit_rule=exit_rule,
        )


def test_engine_contract_is_versioned_and_broker_independent():
    engine = BacktestEngine()
    assert engine.ENGINE_VERSION == "R69.2-v1"
    assert engine.EXECUTION_MODEL == "signal_close_fill_next_open"
    assert engine.POSITION_SIZING == "all_available_cash_integer_shares"
