"""Owner EMA horizon restrictions, causal signals, and old-position exits."""

from copy import deepcopy

import pytest

from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
from scanner import approved_strategies as rules
from scanner.strategy_horizons import horizon_strategy, scanner_horizon_choices
from scanner.strategy_registry import REGISTRY_VERSION, get_strategy
from services.approved_paper_plan import from_signal, is_approved, validate
from tests.test_approved_horizon_strategies import pair

# Frozen pre-pause execution/lineage contract, not current scanner admission.
pytestmark = pytest.mark.usefixtures("previous_horizon_scope")


@pytest.mark.parametrize(
    "n,allowed",
    [
        (1, {"intraday"}),
        (7, {"intraday"}),
        (12, {"intraday"}),
        (13, {"intraday"}),
        (3, {"short_swing", "short_term"}),
        (14, {"short_swing", "short_term"}),
        (15, {"short_swing", "short_term"}),
        (5, {"long_term"}),
        (6, {"long_term"}),
        (16, {"long_term"}),
        (17, {"long_term"}),
        (18, {"long_term"}),
        (19, {"long_term"}),
    ],
)
def test_research_catalog_and_api_reject_every_disallowed_horizon(n, allowed):
    key = rules.IDS[n - 1]
    for horizon in (
        "intraday",
        "short_swing",
        "short_term",
        "medium_term",
        "long_term",
    ):
        if horizon in allowed:
            choice = horizon_strategy(horizon, key)
            assert choice["mode"] == (
                "intraday"
                if horizon == "intraday"
                else "positional"
                if horizon == "long_term"
                else "swing"
            )
        else:
            with pytest.raises(ValueError, match="unavailable"):
                horizon_strategy(horizon, key)


def test_visible_intraday_ema_definitions_never_use_slow_horizon_averages():
    for choice in scanner_horizon_choices("intraday").values():
        row = get_strategy(choice["strategy_id"])
        emas = {
            indicator for indicator in row["indicators"] if indicator.startswith("EMA_")
        }
        assert not emas & {"EMA_20", "EMA_50", "EMA_100", "EMA_200"}
    for horizon in ("short_swing", "short_term"):
        for choice in scanner_horizon_choices(horizon).values():
            row = get_strategy(choice["strategy_id"])
            emas = {
                indicator
                for indicator in row["indicators"]
                if indicator.startswith("EMA_")
            }
            assert not emas & {"EMA_9", "EMA_26", "EMA_100", "EMA_200"}


def test_ema26_cross_drives_new_entries_even_when_ema20_disagrees():
    key, context, previous, row = pair(1)
    previous["EMA_9"], previous["EMA_26"], previous["EMA_20"] = 100.0, 101.0, 99.0
    row["EMA_9"], row["EMA_26"], row["EMA_20"] = 102.0, 101.0, 103.0
    assert rules.evaluate(previous, row, context, key)["signal"] == "BUY"
    row["EMA_26"] = 103.0
    assert rules.evaluate(previous, row, context, key)["signal"] != "BUY"


def test_ema26_reversal_and_original_ema20_exit_are_kept_separate():
    key, context, previous, row = pair(1)
    previous["EMA_9"], previous["EMA_26"], previous["EMA_20"] = 102.0, 101.0, 103.0
    row["EMA_9"], row["EMA_26"], row["EMA_20"] = 100.0, 101.0, 99.0
    plan = rules.plan_for(key, row, context)
    assert (
        rules.closed_exit(previous, row, deepcopy(plan), context)
        == "EMA9_26_REVERSAL_EXIT"
    )
    legacy = rules.context_for(key, "intraday", policy_version=rules.LEGACY_VERSION)
    old = rules.plan_for(key, row, legacy)
    assert rules.closed_exit(previous, row, old, legacy) is None
    row["EMA_20"] = 101.0
    previous["EMA_20"] = 100.0
    assert rules.closed_exit(previous, row, old, legacy) == "EMA9_20_REVERSAL_EXIT"


@pytest.mark.parametrize(
    "n,mode,horizon",
    [
        (1, "intraday", "intraday"),
        (5, "swing", "medium_term"),
        (12, "swing", "short_swing"),
        (14, "intraday", "intraday"),
        (16, "intraday", "intraday"),
        (16, "swing", "medium_term"),
        (18, "intraday", "intraday"),
        (15, "intraday", "intraday"),
        (17, "intraday", "intraday"),
        (19, "intraday", "intraday"),
    ],
)
def test_old_paper_plans_can_restore_but_cannot_open_new_entries(n, mode, horizon):
    key, _, _, row = pair(n)
    context = rules.context_for(
        key, mode, horizon=horizon, policy_version=rules.LEGACY_VERSION
    )
    plan = rules.plan_for(key, row, context)
    assert plan and is_approved(plan)
    rebuilt = from_signal(key, plan, plan["entry"])
    assert rebuilt["policy_version"] == rules.LEGACY_VERSION
    assert rebuilt["horizon"] == horizon
    kwargs = dict(
        entry=plan["entry"],
        stop=plan["stoploss"],
        target=plan.get("target2") or 0.0,
        mode=mode,
    )
    assert validate(key, plan, restoring=True, **kwargs) == plan
    with pytest.raises(ValueError, match="current approved policy"):
        validate(key, plan, restoring=False, **kwargs)


@pytest.mark.parametrize(
    "n,mode,horizon",
    [
        (1, "intraday", "intraday"),
        (5, "swing", "medium_term"),
        (14, "intraday", "intraday"),
        (16, "swing", "medium_term"),
        (15, "intraday", "intraday"),
        (17, "intraday", "intraday"),
        (19, "intraday", "intraday"),
    ],
)
def test_persisted_v1_trades_restore_and_monitor_after_horizon_removal(
    n, mode, horizon, tmp_path, monkeypatch
):
    from core.database import initialize_database
    from database.repositories.trade_repository import TradeRepository
    from services.approved_paper_plan import advance
    from services.paper_trading_runtime import PaperTradingRuntime

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "legacy.db"))
    initialize_database()
    key, _, previous, row = pair(n)
    context = rules.context_for(
        key, mode, horizon=horizon, policy_version=rules.LEGACY_VERSION
    )
    plan = rules.plan_for(key, row, context)
    repo = TradeRepository()
    repo.save(
        "ABC",
        "SHORT" if plan["direction"] < 0 else "BUY",
        4,
        plan["entry"],
        stoploss=plan["stoploss"],
        target=plan.get("target2") or 0.0,
        created_at=previous.name.isoformat(),
        trade_mode=mode,
        strategy_id=key,
        paper_plan=plan,
    )
    runtime = PaperTradingRuntime(trades=repo)
    try:
        assert runtime.restore_open() == 1
        assert (
            runtime.portfolio.positions["ABC"].paper_plan["policy_version"]
            == rules.LEGACY_VERSION
        )
        advance(runtime, "ABC", previous, row)
        assert runtime.portfolio.positions["ABC"].paper_plan["last_candle_at"]
    finally:
        runtime.close()


@pytest.mark.parametrize("n", [5, 6, 16, 18])
def test_long_term_plans_keep_yearly_partial_targets_and_conditional_stops(n):
    key, context, _, row = pair(n)
    plan = rules.plan_for(key, row, context)
    assert plan["annual"] and plan["mode"] == "positional"
    assert plan["partial_target"] == row["FIB_YEAR_R1"]
    assert plan["second_target"] == row["FIB_YEAR_R2"]
    assert plan["target2"] == row["FIB_YEAR_R3"]
    assert not plan["stop_is_resting_order"]


def test_old_registry_evidence_is_invalidated_and_new_pair_count_is_explicit():
    assert REGISTRY_VERSION == "strategy-v15-short-long-institutional-ratings"
    engine = MultiStrategyBacktestEngine()
    pairs = []
    for key in rules.IDS:
        for mode in get_strategy(key)["modes"]:
            if not rules.exit_only(key, mode):
                assert engine.validate_strategy(key, mode=mode)
                pairs.append((key, mode))
    assert len(pairs) == 16
    for key in (rules.IDS[4], rules.IDS[15], rules.IDS[17]):
        for mode in ("intraday", "swing"):
            with pytest.raises(ValueError, match="not registered"):
                engine.validate_strategy(key, mode=mode)
