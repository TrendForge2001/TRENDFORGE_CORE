"""Current approved rules: signal roles, causal references and execution parity."""

from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest.approved_strategy_engine import ApprovedStrategyBacktestEngine
from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
from indicators.approved_strategies import add_native, attach_references, reference_maps
from scanner import approved_strategies as rules
from scanner.strategy_horizons import horizon_strategies
from scanner.strategy_registry import get_strategy
from services.approved_paper_plan import from_signal
from services.execution_report import validate_result
from services.paper_trading_runtime import PaperTradingRuntime
from services.staged_paper_plan import validate_plan

# Frozen pre-pause execution/lineage contract, not current scanner admission.
pytestmark = pytest.mark.usefixtures("previous_horizon_scope")


def sessions_with_non_trading_history(special_start="18:00"):
    _, _, previous, trigger = pair(1)
    sessions = []
    for day in ("2026-11-06", "2026-11-09"):
        index = pd.date_range(
            day + " 09:15", day + " 15:15", freq="15min", tz="Asia/Kolkata"
        )
        sessions.extend(
            pd.Series(previous if i == 0 else trigger, name=stamp)
            for i, stamp in enumerate(index)
        )
    evening = pd.date_range(
        "2026-11-08 " + special_start, periods=3, freq="15min", tz="Asia/Kolkata"
    )
    special = [
        pd.Series(previous if i == 0 else trigger, name=stamp)
        for i, stamp in enumerate(evening)
    ]
    return pd.DataFrame(sessions).sort_index(), pd.DataFrame(
        sessions + special
    ).sort_index()


@pytest.mark.parametrize("timezone", ["Asia/Kolkata", "UTC", None])
@pytest.mark.parametrize("special_start", ["18:00", "14:20", "13:20"])
def test_non_trading_session_retains_prices_without_inventing_square_off_or_entries(
    timezone,
    special_start,
):
    normal, full = sessions_with_non_trading_history(special_start)
    if timezone is None:
        full.index = full.index.tz_localize(None)
    else:
        full.index = full.index.tz_convert(timezone)
    engine = ApprovedStrategyBacktestEngine()
    kwargs = dict(strategy_id=rules.IDS[0], mode="intraday", interval="15m")
    baseline = engine.run({"ABC": normal}, **kwargs)
    result = engine.run({"ABC": full}, **kwargs)
    assert result["metrics"]["non_regular_sessions"] == 1
    assert result["metrics"]["net_profit"] == pytest.approx(
        baseline["metrics"]["net_profit"]
    )
    assert len(result["trades"]) == len(baseline["trades"]) == 2
    for trade in result["trades"]:
        entered, exited = map(pd.Timestamp, (trade["entry_at"], trade["exit_at"]))
        assert entered.date() == exited.date()
        assert (entered.hour, entered.minute) == (9, 45)
        assert (exited.hour, exited.minute) == (15, 0)
        assert trade["exit_reason"] == "INTRADAY_SQUARE_OFF"


def test_missing_regular_session_square_off_still_fails_with_evening_history():
    _, full = sessions_with_non_trading_history("14:20")
    full = full.drop(pd.Timestamp("2026-11-06 15:00", tz="Asia/Kolkata"))
    with pytest.raises(ValueError, match="missing its 15:00"):
        ApprovedStrategyBacktestEngine().run(
            {"ABC": full}, strategy_id=rules.IDS[0], mode="intraday", interval="15m"
        )


def pair(n, mode=None):
    key = rules.IDS[n - 1]
    mode = mode or (
        "intraday"
        if "intraday" in rules.horizons(key)
        else "positional"
        if "long_term" in rules.horizons(key)
        else "swing"
    )
    context = rules.context_for(key, mode)
    short = key in rules.BEARISH
    close = 90.0 if short else 110.0
    row = {
        "open": 95.0 if short else 105.0,
        "high": 101.0 if short else 112.0,
        "low": 88.0 if short else 99.0,
        "close": close,
        "volume": 200.0,
        "VOL_SMA_20": 100.0,
        "VOL_SMA_20_PREV": 100.0,
        "RSI_WILDER_14": 40.0 if short else 60.0,
        "EMA_RESEARCH_BARS": 301.0,
        "VWAP_SESSION": 100.0,
        "LOW_20_PREV": 95.0,
        "EMA_HIGH_9": 100.0,
        "SWING_HIGHS_20": (118.0, 120.0),
        "SWING_LOWS_20": (82.0, 80.0),
        "ADX": 30.0,
        "+DI": 10.0,
        "-DI": 30.0,
        "FIB_MONTH_LOW": 70.0,
    }
    for name in (
        "EMA_9",
        "EMA_20",
        "EMA_26",
        "EMA_50",
        "EMA_100",
        "EMA_200",
        "VWMA_9",
        "VWMA_26",
    ):
        row[name] = 100.0 if short else 108.0
    if n <= 8:
        fast, slow = (
            (9, 26)
            if n in (1, 7)
            else (9, 26)
            if n in (2, 4, 8)
            else (20, 50)
            if n == 3
            else (50, 100)
            if n == 5
            else (100, 200)
        )
        prefix = "VWMA" if key in rules.VWMA else "EMA"
    elif n >= 12:
        setup = rules.EMA_PIVOT_SETUPS[key]
        fast, slow, prefix = setup.fast, setup.slow, "EMA"
    else:
        fast, slow, prefix = 9, 20, "EMA"
    row[f"{prefix}_{fast}"] = 99.0 if short else 109.0
    row[f"{prefix}_{slow}"] = 100.0 if short else 108.0
    for period in ("DAY", "WEEK", "MONTH", "YEAR"):
        for level, value in dict(
            P=100.0, S1=80.0, S2=60.0, S3=40.0, R1=120.0, R2=140.0, R3=160.0
        ).items():
            row[f"FIB_{period}_{level}"] = value
    previous = {
        **row,
        f"{prefix}_{fast}": 101.0 if short else 107.0,
        "close": 110.0 if n == 9 else close,
    }
    previous["high"] = max(previous["high"], previous["open"], previous["close"])
    stamps = pd.date_range(
        "2026-03-02 10:00" if mode == "intraday" else "2026-03-02",
        periods=2,
        freq="15min" if mode == "intraday" else "B",
        tz="Asia/Kolkata",
    )
    return (
        key,
        context,
        pd.Series(previous, name=stamps[0]),
        pd.Series(row, name=stamps[1]),
    )


@pytest.mark.parametrize("n", range(1, 20))
def test_all_nineteen_have_approved_executable_native_rules(n):
    key, context, previous, row = pair(n)
    result = rules.evaluate(previous, row, context, key)
    assert get_strategy(key)["implementation_status"] == rules.STATUS
    only_exit = rules.exit_only(key, context.mode)
    assert result["signal"] == (
        "EXIT" if only_exit else "SELL" if key in rules.BEARISH else "BUY"
    ), result["failed_checks"]
    if not only_exit:
        assert result["entry_plan"]["policy_version"] == rules.VERSION
        assert (
            key
            in MultiStrategyBacktestEngine().readiness()["backtestable_strategy_ids"]
        )


@pytest.mark.parametrize("n", [n for n in range(1, 20) if n not in (15, 17, 19)])
def test_all_entry_strategies_real_route_simulations_reconcile_cash_and_fees(n):
    key, context, previous, row = pair(n)
    step = (
        pd.Timedelta(minutes=15) if context.mode == "intraday" else pd.Timedelta(days=1)
    )
    entered = row.copy()
    entered.name += step
    entered["open"] = entered["close"]
    entered["high"], entered["low"] = entered["close"] + 1, entered["close"] - 1
    frame = pd.DataFrame([previous, row, entered])
    result = ApprovedStrategyBacktestEngine().run(
        {"ABC": frame},
        strategy_id=key,
        mode=context.mode,
        interval=context.interval,
        short_borrow_available=True,
    )
    assert result["metrics"]["total_trades"] == 1, result["rejection_counts"]
    trade = result["trades"][0]
    assert trade["entry_at"] == entered.name.isoformat()
    assert result["metrics"]["net_profit"] == pytest.approx(
        sum(t["net_pnl"] for t in result["trades"])
    )
    assert trade["net_pnl"] == pytest.approx(
        trade["gross_pnl"] - trade["transaction_costs"]
    )
    assert result["metrics"]["max_capital_committed"] <= 100_000
    assert result["metrics"]["minimum_cash"] >= 0
    single = MultiStrategyBacktestEngine().run(
        frame,
        strategy_id=key,
        mode=context.mode,
        interval=context.interval,
        cost_bps=12,
        slippage_bps=5,
        short_borrow_available=True,
    )
    assert single.metrics["net_profit"] == pytest.approx(
        result["metrics"]["net_profit"]
    )


@pytest.mark.parametrize(
    "n,horizon",
    [(15, "short_swing"), (15, "short_term"), (17, "long_term"), (19, "long_term")],
)
def test_bearish_nonintraday_is_scanner_exit_only(n, horizon):
    mode = "positional" if n in (17, 19) else "swing"
    key, _, previous, row = pair(n)
    row.name = pd.Timestamp("2026-03-03", tz="Asia/Kolkata")
    previous.name = row.name - pd.Timedelta(days=1)
    context = rules.context_for(key, mode, horizon=horizon)
    assert rules.evaluate(previous, row, context, key)["signal"] == "EXIT"
    assert not rules.plan_for(key, row, context)
    with pytest.raises(ValueError, match="exit-only"):
        MultiStrategyBacktestEngine().validate_strategy(key, mode=mode)


def test_horizon_choices_move_ema50_100_from_medium_to_long_term():
    assert not horizon_strategies("medium_term")
    assert rules.IDS[4] in {
        r["strategy_id"] for r in horizon_strategies("long_term").values()
    }
    assert rules.IDS[5] in {
        r["strategy_id"] for r in horizon_strategies("long_term").values()
    }
    assert all(
        not r["short_borrow_available"]
        for r in horizon_strategies("medium_term").values()
    )


@pytest.mark.parametrize("n", [2, 4, 8])
@pytest.mark.parametrize("missing", ["RSI_WILDER_14", "VOL_SMA_20", "volume"])
def test_vwma_entry_and_exit_require_both_confirmations(n, missing):
    key, context, previous, row = pair(n)
    plan = rules.plan_for(key, row, context)
    assert plan
    blocked = row.copy()
    blocked[missing] = float("nan")
    assert rules.evaluate(previous, blocked, context, key)["signal"] != (
        "SELL" if n == 8 else "BUY"
    )
    sign = plan["direction"]
    exiting = row.copy()
    exiting["close"] = plan["stoploss"] - sign * 5
    exiting["VWMA_9"] = exiting["VWMA_26"] - sign * 2
    exiting["RSI_WILDER_14"] = 60 if sign < 0 else 40
    assert rules.closed_exit(previous, exiting, deepcopy(plan), context)
    exiting[missing] = float("nan")
    assert rules.closed_exit(previous, exiting, deepcopy(plan), context) is None


def test_ema50_needs_two_post_entry_daily_closes_and_resets():
    key, context, previous, row = pair(3)
    plan = rules.plan_for(key, row, context)
    plan["trail_ema"] = 50.0
    plan["entry_at"] = previous.name.isoformat()
    previous["EMA_20"], row["EMA_20"] = 50.0, 50.0
    previous["close"], row["close"] = 107.0, 107.0
    assert (
        rules.closed_exit(previous, row, deepcopy(plan), context)
        == "EMA50_TWO_DAILY_CLOSES_STOP"
    )
    previous["close"] = previous["EMA_50"]
    assert rules.closed_exit(previous, row, deepcopy(plan), context) is None
    plan["entry_at"] = row.name.isoformat()
    previous["close"] = 100.0
    assert rules.closed_exit(previous, row, deepcopy(plan), context) is None
    row["EMA_20"] = 109.0
    assert (
        rules.closed_exit(previous, row, deepcopy(plan), context)
        == "EMA20_TRAILING_EXIT"
    )


def test_price_only_vwma_breach_is_never_quote_stop():
    key, context, _, row = pair(2)
    plan = rules.plan_for(key, row, context)
    position = SimpleNamespace(
        side="BUY",
        trade_mode="intraday",
        entry_at="2026-03-02T10:30:00+05:30",
        stoploss=plan["stoploss"],
        target2=0.0,
        paper_plan=plan,
    )
    assert (
        PaperTradingRuntime._exit_reason(
            position,
            plan["stoploss"] - 5,
            pd.Timestamp("2026-03-02 11:00", tz="Asia/Kolkata"),
        )
        is None
    )
    assert (
        PaperTradingRuntime._exit_reason(
            position, 100.0, pd.Timestamp("2026-03-02 15:00", tz="Asia/Kolkata")
        )
        == "FORCE_EXIT_15_00_IST"
    )


@pytest.mark.parametrize("n", [n for n in range(1, 20) if n not in (15, 17, 19)])
def test_paper_plan_revalidates_actual_fill_and_rejects_tampering(n):
    key, context, _, row = pair(n)
    plan = rules.plan_for(key, row, context)
    plan = from_signal(key, plan, row["close"] + 0.1)
    checked = validate_plan(
        key,
        plan,
        entry=plan["entry"],
        stop=plan["stoploss"],
        target=plan.get("target2") or 0.0,
        mode=context.mode,
    )
    assert checked["direction"] == plan["direction"]
    corrupted = deepcopy(plan)
    corrupted["initial_stop"] += 1
    with pytest.raises(ValueError):
        validate_plan(
            key,
            corrupted,
            entry=plan["entry"],
            stop=plan["stoploss"],
            target=plan.get("target2") or 0.0,
            mode=context.mode,
        )


def test_confirmed_swing_uses_two_right_bars_before_trigger_and_ema_on_highs():
    frame = pd.DataFrame(
        dict(
            high=[100, 101, 110, 103, 104, 105],
            low=[90, 91, 92, 93, 94, 95],
            close=[95] * 6,
            volume=[100] * 6,
        ),
        index=pd.date_range("2026-03-01", periods=6),
    )
    output = add_native(frame)
    assert output.iloc[4]["SWING_HIGHS_20"] == ()
    assert output.iloc[5]["SWING_HIGHS_20"] == (110.0,)
    assert output.iloc[-1]["EMA_HIGH_9"] == pytest.approx(
        frame.high.ewm(span=9, adjust=False).mean().iloc[-1]
    )
    prefix = add_native(frame.iloc[:5])
    pd.testing.assert_frame_equal(prefix, output.iloc[:5])


def test_reference_pivots_use_completed_previous_period_and_ignore_future():
    index = pd.bdate_range("2025-01-01", "2026-03-31", tz="Asia/Kolkata")
    daily = pd.DataFrame(
        dict(high=120.0, low=80.0, close=100.0, open=100.0, volume=100.0), index=index
    )
    signal = daily.loc["2026-03-02":"2026-03-04"]
    before = attach_references(signal, reference_maps(daily.loc[:"2026-03-04"]))
    changed = daily.copy()
    changed.loc["2026-03-05":, "high"] = 1000.0
    after = attach_references(signal, reference_maps(changed))
    pd.testing.assert_frame_equal(before, after)
    assert before.iloc[-1]["FIB_WEEK_R1"] == pytest.approx(115.28)
    assert before.iloc[-1]["FIB_MONTH_LOW"] == 80.0


def test_annual_half_r1_final_r3_and_report_ledger_reconcile():
    key, context, previous, row = pair(5)
    entry = row.copy()
    entry.name += pd.Timedelta(days=1)
    entry["open"], entry["high"], entry["low"], entry["close"] = (
        110.0,
        121.0,
        109.0,
        120.0,
    )
    final = entry.copy()
    final.name += pd.Timedelta(days=1)
    final["open"], final["high"], final["close"] = 121.0, 161.0, 160.0
    result = ApprovedStrategyBacktestEngine().run(
        {"ABC": pd.DataFrame([previous, row, entry, final])},
        strategy_id=key,
        mode=context.mode,
        interval=context.interval,
    )
    legs = result["exit_fills"]
    assert [leg["exit_reason"] for leg in legs] == [
        "R1_PARTIAL_PROFIT",
        "R3_FINAL_TARGET",
    ]
    assert legs[0]["quantity"] == result["trades"][0]["quantity"] // 2
    validate_result(
        {
            **result,
            "status": "completed",
            "parameters": {
                "deployment_limit": 100_000.0,
                "cash_reserve": 0.0,
                "max_positions": 3,
            },
            "symbols": ["ABC"],
            "mode": "swing",
            "strategy_id": key,
        }
    )


@pytest.mark.parametrize("n", [n for n in range(1, 20) if n not in (15, 17, 19)])
def test_durable_paper_open_restore_and_conditional_stop_behavior(
    n, tmp_path, monkeypatch
):
    from core.database import initialize_database
    from database.repositories.trade_repository import TradeRepository

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "paper.db"))
    initialize_database()
    key, context, _, row = pair(n)
    plan = rules.plan_for(key, row, context)
    runtime = PaperTradingRuntime(trades=TradeRepository())
    entered = (
        pd.Timestamp("2026-03-03 10:30", tz="Asia/Kolkata")
        if context.mode != "intraday"
        else row.name + pd.Timedelta(minutes=15)
    )
    order = SimpleNamespace(
        symbol="ABC",
        side="SHORT" if plan["direction"] < 0 else "BUY",
        price=plan["entry"],
        quantity=4 if plan["annual"] else 1,
        stoploss=plan["stoploss"],
        target2=plan.get("target2") or 0.0,
        trade_mode=context.mode,
        strategy_id=key,
        paper_plan=plan,
    )
    runtime.open(order, now=entered)
    if not plan["stop_is_resting_order"]:
        mark = plan["stoploss"] - plan["direction"] * 1
        assert runtime.monitor({"ABC": mark}, now=entered) == []
        assert "ABC" in runtime.portfolio.positions
    restored = PaperTradingRuntime(trades=TradeRepository())
    assert restored.restore_open() == 1
    position = restored.portfolio.positions["ABC"]
    assert position.paper_plan["policy_version"] == rules.VERSION
    assert position.paper_plan["initial_stop"] == plan["initial_stop"]
    assert position.quantity == order.quantity
    runtime.close()
    restored.close()


def test_pending_exit_is_durable_and_retried_after_quote_failure(tmp_path, monkeypatch):
    from core.database import initialize_database
    from database.repositories.trade_repository import TradeRepository
    from services.approved_paper_plan import advance

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "paper.db"))
    initialize_database()
    key, context, previous, row = pair(2)
    plan = rules.plan_for(key, row, context)
    runtime = PaperTradingRuntime(trades=TradeRepository())
    now = row.name + pd.Timedelta(minutes=15)
    runtime.open(
        SimpleNamespace(
            symbol="ABC",
            side="BUY",
            quantity=1,
            price=plan["entry"],
            stoploss=plan["stoploss"],
            target2=0.0,
            strategy_id=key,
            trade_mode="intraday",
            paper_plan=plan,
        ),
        now=now,
    )
    exiting = row.copy()
    exiting.name = now
    exiting["close"], exiting["VWMA_9"], exiting["RSI_WILDER_14"] = 95.0, 99.0, 40.0
    reason = advance(runtime, "ABC", row, exiting)
    assert reason == "VWMA26_CONFIRMED_STOP"
    restored = PaperTradingRuntime(trades=TradeRepository())
    restored.restore_open()
    assert advance(restored, "ABC", row, exiting) == reason
    assert (
        restored.portfolio.positions["ABC"].paper_plan["last_candle_at"]
        == now.isoformat()
    )
    runtime.close()
    restored.close()


def test_daily_vwma_stops_and_profit_limits_require_causal_rsi_and_volume():
    from scanner.vwma_yearly import (
        opening_gap_exit,
        profit_confirmation,
        stop_conditions,
    )

    _, _, previous, row = pair(4)
    row["open"], row["close"], row["RSI_WILDER_14"] = 105.0, 70.0, 29.0
    assert stop_conditions(previous, row, 80.0, vwma_confirmation=True)[
        "rsi_below_30_and_gap_down"
    ]
    row["volume"] = 80.0
    assert not any(
        stop_conditions(previous, row, 80.0, vwma_confirmation=True).values()
    )
    previous["RSI_WILDER_14"] = 29.0
    previous["volume"] = 80.0
    assert not opening_gap_exit(previous, row, vwma_confirmation=True)
    previous["RSI_WILDER_14"] = 60.0
    previous["volume"] = 120.0
    assert profit_confirmation(previous)
    # The partial current candle can never confirm a resting profit limit.
    row["volume"], row["RSI_WILDER_14"] = 10000.0, 70.0
    previous["volume"] = 80.0
    assert not profit_confirmation(previous)


@pytest.mark.parametrize("n", [2, 5, 9])
def test_public_portfolio_report_keeps_native_metadata_auxiliaries_and_export(
    n, tmp_path
):
    from core.database import initialize_database
    from database.repositories.backtest_results import BacktestResultsRepository
    from services.portfolio_backtest_service import PortfolioBacktestService
    from services.technical_trading_service import TechnicalTradingService
    from tests.test_vwma_yearly_research import history

    key, context, previous, row = pair(n)
    step = (
        pd.Timedelta(minutes=15) if context.mode == "intraday" else pd.Timedelta(days=1)
    )
    entered = row.copy()
    entered.name += step
    entered["open"] = entered["close"]
    entered["high"], entered["low"] = entered["close"] + 1, entered["close"] - 1
    # Full warm-up is calculated before the selected execution window.
    if context.mode == "intraday":
        padding = (
            pd.date_range(
                "2026-02-25 09:15", periods=24, freq="15min", tz="Asia/Kolkata"
            )
            .append(
                pd.date_range(
                    "2026-02-26 09:15", periods=24, freq="15min", tz="Asia/Kolkata"
                )
            )
            .append(
                pd.date_range(
                    "2026-02-27 09:15", periods=24, freq="15min", tz="Asia/Kolkata"
                )
            )
        )
    else:
        padding = pd.bdate_range(
            start=pd.Timestamp("2022-01-03", tz="Asia/Kolkata"),
            end=previous.name - pd.Timedelta(days=1),
        )
    frame = pd.concat(
        [
            pd.DataFrame([previous.to_dict()] * len(padding), index=padding),
            pd.DataFrame([previous, row, entered]),
        ]
    )

    # No spurious trigger during padding; last pair has the approved cross.
    class Market:
        def batch_candles_with_errors(self, symbols, **kwargs):
            return {
                s: history()
                if kwargs["interval"] == "1d" and context.mode == "intraday"
                else frame.copy()
                for s in symbols
            }, {}

    path = str(tmp_path / "reports.db")
    initialize_database(path)
    technical = TechnicalTradingService(
        market_data=Market(),
        repository=BacktestResultsRepository(db_path=path),
        indicator_engine=SimpleNamespace(calculate=lambda f: f),
    )
    try:
        result = PortfolioBacktestService(technical).run(
            symbols=["ABC"],
            mode=context.mode,
            strategy_id=key,
            period="30d" if context.mode == "intraday" else "2y",
            now=pd.Timestamp("2026-03-05 18:00", tz="Asia/Kolkata"),
            short_borrow_available=True,
        )
        validate_result(result)
        assert result["engine"]["name"] == "ApprovedStrategyBacktestEngine"
        assert result["parameters"]["exit_policy_version"] == rules.VERSION
        assert result["report"]["xlsx_base64"]
        assert technical.repository.by_run_id(result["run_id"])
    finally:
        technical.repository.close()


def test_paper_monitor_prioritizes_pending_completed_exit_over_new_quote_targets(
    tmp_path, monkeypatch
):
    from core.database import initialize_database
    from database.repositories.trade_repository import TradeRepository
    from services.paper_trading_service import PaperTradingService
    from services.strategy_paper_monitor_service import StrategyPaperMonitorService

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "paper.db"))
    initialize_database()
    key, context, previous, row = pair(5)
    plan = rules.plan_for(key, row, context)
    runtime = PaperTradingRuntime(trades=TradeRepository())
    runtime.open(
        SimpleNamespace(
            symbol="ABC",
            side="BUY",
            price=110.0,
            quantity=4,
            stoploss=plan["stoploss"],
            target2=plan["target2"],
            strategy_id=key,
            trade_mode=context.mode,
            paper_plan=plan,
        ),
        now=pd.Timestamp("2026-03-04 10:00", tz="Asia/Kolkata"),
    )
    exiting = row.copy()
    exiting.name += pd.Timedelta(days=1)
    exiting["open"], exiting["close"], exiting["RSI_WILDER_14"] = 105.0, 102.0, 29.0
    padding = pd.bdate_range(
        end=previous.name - pd.Timedelta(days=1), periods=130, tz="Asia/Kolkata"
    )
    frame = pd.concat(
        [
            pd.DataFrame([previous.to_dict()] * len(padding), index=padding),
            pd.DataFrame([previous, row, exiting]),
        ]
    )
    scanner = SimpleNamespace(
        _mode_config=lambda *a: (context.mode, "1d", "5y"),
        market_data=SimpleNamespace(
            batch_candles_with_errors=lambda *a, **k: ({"ABC": frame}, {})
        ),
        indicators=SimpleNamespace(calculate=lambda f: f),
        _completed_bars=lambda f, **k: f,
        _label=lambda s: s.isoformat(),
    )
    paper = PaperTradingService(runtime, enabled=True, environment_kill_switch=False)
    monitor = StrategyPaperMonitorService(
        scanner_service=scanner,
        paper_service=paper,
        quote_provider=SimpleNamespace(
            ltp=lambda instruments: {s: {"last_price": 160.0} for s in instruments}
        ),
        enabled=True,
    )
    result = monitor.tick(now=pd.Timestamp("2026-03-05 10:00", tz="Asia/Kolkata"))
    assert not [r.get("error") for r in result["evaluations"] if r.get("error")]
    assert not result["close_errors"]
    assert len(result["closed"]) == 1, result["evaluations"]
    assert result["closed"][0]["exit_signal"] == "RSI_GAP_CLOSE_CONFIRMED_EXIT"
    saved = runtime.trades.strategy_trades(key)
    assert len(saved) == 1 and saved[0]["quantity"] == 4
    assert runtime.portfolio.positions == {}
    runtime.close()


def test_paper_automation_honors_the_saved_short_availability_switch():
    from services.strategy_paper_automation import StrategyPaperAutomation

    automation = object.__new__(StrategyPaperAutomation)
    automation._now = lambda: pd.Timestamp("2026-03-02 10:30", tz="Asia/Kolkata")
    automation._assume_short_borrow = False
    with pytest.raises(ValueError, match="short availability"):
        automation._live_candidate(
            {
                "strategy_id": rules.IDS[7],
                "symbol": "ABC",
                "technical_mode": "intraday",
                "entry_bar_at": "2026-03-02T10:15:00+05:30",
            }
        )


def test_nonintraday_bearish_scan_reports_an_exit_of_a_long(tmp_path):
    from core.database import initialize_database
    from database.repositories.backtest_results import BacktestResultsRepository
    from services.technical_trading_service import TechnicalTradingService

    key, _, previous, row = pair(15)
    index = pd.bdate_range("2025-09-01", periods=80, tz="Asia/Kolkata")
    frame = pd.DataFrame([previous.to_dict()] * 79 + [row.to_dict()], index=index)
    path = str(tmp_path / "scan.db")
    initialize_database(path)
    technical = TechnicalTradingService(
        market_data=SimpleNamespace(
            batch_candles_with_errors=lambda *a, **k: ({"ABC": frame}, {})
        ),
        repository=BacktestResultsRepository(db_path=path),
        indicator_engine=SimpleNamespace(calculate=lambda f: f),
    )
    technical.yearly_references = SimpleNamespace(enrich_approved=lambda f, **k: f)
    try:
        result = technical.scan(
            symbols=["ABC"],
            mode="swing",
            strategy_id=key,
            period="2y",
            horizon="short_swing",
            now=pd.Timestamp("2026-03-05 10:00", tz="Asia/Kolkata"),
        )
        signal = result["results"][0]
        assert signal["signal"] == "EXIT" and signal["side"] == "LONG"
        assert signal["execution_eligible"] is False
    finally:
        technical.repository.close()
