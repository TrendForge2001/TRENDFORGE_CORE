from __future__ import annotations

import pandas as pd

from scanner.multi_strategy_engine import MultiStrategyEngine


def _frame() -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-10-20 09:45", tz="Asia/Kolkata"),
            pd.Timestamp("2026-10-20 10:00", tz="Asia/Kolkata"),
        ]
    )
    return pd.DataFrame(
        {
            "open": [99.0, 100.0],
            "high": [101.0, 103.0],
            "low": [98.0, 99.0],
            "close": [100.0, 102.0],
            "volume": [100.0, 200.0],
            "EMA_9": [99.0, 101.0],
            "EMA_20": [100.0, 100.0],
            "EMA_50": [95.0, 95.0],
            "EMA_100": [93.0, 93.0],
            "EMA_200": [90.0, 90.0],
            "VWMA_9": [99.0, 101.0],
            "VWMA_26": [100.0, 100.0],
            "RSI_14": [58.0, 65.0],
            "RSI_20": [57.0, 63.0],
            "VOL_SMA_20": [120.0, 150.0],
            "VOL_SMA_50": [110.0, 140.0],
            "ATR": [2.0, 2.0],
            "SUPERTREND_DIR": [1.0, 1.0],
            "SUPERTREND_10_3": [96.0, 97.0],
            "ADX": [22.0, 25.0],
            "+DI": [25.0, 30.0],
            "-DI": [15.0, 10.0],
            "VWAP": [99.5, 100.5],
            "RVOL": [0.9, 1.4],
            "BREAKOUT": [False, True],
            "BREAKDOWN": [False, False],
            "MACD": [0.2, 0.8],
            "MACD_SIGNAL": [0.3, 0.5],
            "MACD_HIST": [-0.1, 0.3],
            "BB_UPPER": [101.0, 101.5],
            "BB_MID": [99.0, 100.0],
            "BB_LOWER": [97.0, 98.5],
            "HIGH_252": [104.0, 104.0],
            "LOW_252": [80.0, 80.0],
            "DIST_52W_HIGH_PCT": [3.8, 1.9],
        },
        index=index,
    )


def test_intraday_notebook_ema9_20_buy_is_explainable():
    result = MultiStrategyEngine().evaluate(
        _frame(),
        mode="intraday",
        interval="15m",
        source="user_notebook",
        strategy_ids=["tf_intraday_ema9_20_momentum"],
    )

    assert result["consensus"] == "BUY"
    assert result["buy_strategy_count"] == 1
    row = result["evaluations"][0]
    assert row["signal"] == "BUY"
    assert row["score"] == 100.0
    assert row["failed_checks"] == []
    assert row["risk"]["entry"] == 102.0
    assert row["risk"]["stoploss"] == 99.0


def test_two_strategy_agreement_promotes_strong_buy():
    result = MultiStrategyEngine().evaluate(
        _frame(),
        mode="intraday",
        interval="15m",
        strategy_ids=[
            "tf_intraday_ema9_20_momentum",
            "tpl_supertrend_rsi",
        ],
    )

    assert result["consensus"] == "STRONG_BUY"
    assert result["buy_strategy_count"] == 2
    assert result["notebook_buy_count"] == 1
    assert result["template_buy_count"] == 1


def test_ambiguous_notebook_strategy_is_review_required_not_guessed():
    result = MultiStrategyEngine().evaluate(
        _frame(),
        mode="intraday",
        interval="15m",
        source="user_notebook",
        strategy_ids=["tf_intraday_supertrend_vwap_pivots"],
    )

    row = result["evaluations"][0]
    assert row["status"] == "review_required"
    assert row["signal"] == "REVIEW_REQUIRED"
    assert result["buy_strategy_count"] == 0


def test_rsi_confirmation_never_becomes_standalone_buy():
    result = MultiStrategyEngine().evaluate(
        _frame(),
        mode="intraday",
        interval="15m",
        source="user_notebook",
        strategy_ids=["tf_rsi_momentum_confirmation"],
    )

    row = result["evaluations"][0]
    assert row["signal"] == "CONFIRM_BUY"
    assert row["confirmation_only"] is True
    assert result["buy_strategy_count"] == 0
    assert result["consensus"] == "WATCH"


def test_engine_readiness_exposes_review_boundary_and_no_execution():
    health = MultiStrategyEngine().readiness()
    assert health["version"] == "R72.5.2-v1"
    assert "tf_intraday_supertrend_vwap_pivots" in health[
        "review_required_strategy_ids"
    ]
    assert health["paper_execution_allowed"] is False
    assert health["broker_orders_allowed"] is False
