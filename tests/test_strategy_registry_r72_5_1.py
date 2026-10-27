from __future__ import annotations

import pytest

from scanner.strategy_registry import (
    REGISTRY_VERSION,
    STRATEGIES,
    get_strategy,
    list_strategies,
    registry_readiness,
)


def test_registry_has_unique_ids_and_expected_sources():
    ids = [item.strategy_id for item in STRATEGIES]
    assert len(ids) == len(set(ids))
    assert len(ids) == 8
    readiness = registry_readiness()
    assert readiness["version"] == REGISTRY_VERSION
    assert readiness["user_notebook_strategies"] == 6
    assert readiness["user_analysis_strategies"] == 2
    assert readiness["intraday_short_strategies"] == 2
    assert readiness["template_strategies"] == 0
    assert readiness["execution_wiring"] == "R72.5.6_restart_safe_strategy_paper"
    assert readiness["paper_execution_wiring"] == "explicit_validation_plus_R67.2_gate"
    assert readiness["runtime_persistence_wiring"] == "sqlite_scan_validation_execution_lineage"
    assert readiness["scan_started"] is False
    assert readiness["backtest_started"] is False
    assert readiness["paper_orders_created"] is False


@pytest.mark.parametrize(
    "strategy_id",
    [
        "tf_intraday_ema9_20_momentum",
        "tf_intraday_vwma9_26_rsi_volume",
        "tf_swing_ema20_50_rsi_volume",
        "tf_swing_vwma9_26_rsi_volume",
        "tf_medium_ema50_100",
        "tf_long_ema100_200",
    ],
)
def test_notebook_strategy_ids_are_registered(strategy_id):
    payload = get_strategy(strategy_id)
    assert payload["strategy_id"] == strategy_id
    assert payload["source"] == "user_notebook"
    assert payload["indicators"]


def test_registry_filters_by_mode_and_source():
    intraday = list_strategies(mode="intraday", source="template")
    assert intraday == []
    assert all("intraday" in row["modes"] for row in intraday)
    assert all(row["source"] == "template" for row in intraday)


def test_unknown_strategy_raises_key_error():
    with pytest.raises(KeyError):
        get_strategy("does_not_exist")
