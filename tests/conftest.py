from __future__ import annotations

import os

# Route unit tests inject local services. Production boundary tests enable auth explicitly.
os.environ.setdefault("TRENDFORGE_API_AUTH_REQUIRED", "false")

import pandas as pd
import pytest


@pytest.fixture
def ohlcv_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [99.0, 100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [98.0, 99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0, 103.0],
            "volume": [1000, 1200, 1100, 1400],
        },
        index=pd.date_range("2026-01-01", periods=4, freq="D"),
    )


@pytest.fixture
def multiindex_ohlcv_frame(ohlcv_frame: pd.DataFrame) -> pd.DataFrame:
    frame = ohlcv_frame.copy()
    frame.columns = pd.MultiIndex.from_tuples(
        (column, "ABC") for column in frame.columns
    )
    return frame


@pytest.fixture
def empty_ohlcv_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


@pytest.fixture
def previous_exit_policy(monkeypatch, request):
    """Replay pre-v10 scanner/execution contracts against their frozen policy.

    These tests exercise legacy ATR/short machinery retained for historical
    replays and existing-position lineage. New-policy admission, data feeds,
    scanners and public backtest routes are covered independently in
    test_shared_annual_exit_policy.py; this fixture is opt-in per legacy module.
    """
    import backtest.multi_strategy_backtest_engine as backtests
    import scanner.annual_exit_policy as policy
    import scanner.multi_strategy_engine as engine
    import scanner.strategy_registry as registry

    definitions = tuple(
        registry._HISTORICAL_BY_ID[key]
        for key in registry._HISTORICAL_BY_ID
        if key in registry.ACTIVE_STRATEGY_IDS
    )
    monkeypatch.setattr(registry, "STRATEGIES", definitions)
    monkeypatch.setattr(
        registry, "_BY_ID", {row.strategy_id: row for row in definitions}
    )
    monkeypatch.setattr(engine, "STRATEGIES", definitions)
    monkeypatch.setattr(engine, "_EVALUATORS", dict(engine._NATIVE_EVALUATORS))
    monkeypatch.setattr(backtests, "_EVALUATORS", engine._EVALUATORS)
    monkeypatch.setattr(policy, "AFFECTED", frozenset())
    monkeypatch.setattr(policy, "EXIT_ONLY", frozenset())
    import scanner.strategy_horizons as horizons

    monkeypatch.setattr(horizons, "HORIZONS", horizons.HISTORICAL_HORIZONS)
    if hasattr(request.module, "HORIZONS"):
        monkeypatch.setattr(request.module, "HORIZONS", horizons.HISTORICAL_HORIZONS)
    import scanner.strategy_scope as scope

    monkeypatch.setattr(scope, "PAUSED_HORIZONS", frozenset())

    choices = frozenset(
        {
            "tf_weekly_gap_recovery_ema50_100_floor",
            "tf_daily_vwma20_50_rsi_fibonacci_yearly",
        }
    )
    monkeypatch.setattr(registry, "SCANNER_CHOICE_IDS", choices)
    monkeypatch.setattr(horizons, "SCANNER_CHOICE_IDS", choices)


@pytest.fixture
def annual_v10_policy(monkeypatch, request):
    """Historical v10 annual-policy regression contract before horizon v11."""
    import backtest.multi_strategy_backtest_engine as backtests
    import scanner.multi_strategy_engine as engine
    import scanner.strategy_registry as registry
    import scanner.strategy_horizons as horizons

    monkeypatch.setattr(horizons, "HORIZONS", horizons.HISTORICAL_HORIZONS)
    if hasattr(request.module, "HORIZONS"):
        monkeypatch.setattr(request.module, "HORIZONS", horizons.HISTORICAL_HORIZONS)
    import scanner.strategy_scope as scope

    monkeypatch.setattr(scope, "PAUSED_HORIZONS", frozenset())

    definitions = registry._V10_STRATEGIES
    monkeypatch.setattr(registry, "STRATEGIES", definitions)
    monkeypatch.setattr(
        registry, "_BY_ID", {row.strategy_id: row for row in definitions}
    )
    monkeypatch.setattr(engine, "STRATEGIES", definitions)
    monkeypatch.setattr(engine, "_EVALUATORS", dict(engine._V10_EVALUATORS))
    monkeypatch.setattr(backtests, "_EVALUATORS", engine._EVALUATORS)


@pytest.fixture
def previous_horizon_scope(monkeypatch):
    """Replay the prior 21-strategy catalog; current scope has separate coverage."""
    import scanner.strategy_registry as registry
    import scanner.strategy_horizons as horizons
    import scanner.strategy_scope as scope
    import scanner.multi_strategy_engine as engine

    definitions = registry._PRE_SCOPE_STRATEGIES
    monkeypatch.setattr(registry, "STRATEGIES", definitions)
    monkeypatch.setattr(
        registry, "_BY_ID", {row.strategy_id: row for row in definitions}
    )
    monkeypatch.setattr(
        registry,
        "SCANNER_CHOICE_IDS",
        frozenset(row.strategy_id for row in definitions),
    )
    monkeypatch.setattr(engine, "STRATEGIES", definitions)
    monkeypatch.setattr(horizons, "HORIZONS", horizons.HISTORICAL_HORIZONS)
    monkeypatch.setattr(scope, "PAUSED_HORIZONS", frozenset())
