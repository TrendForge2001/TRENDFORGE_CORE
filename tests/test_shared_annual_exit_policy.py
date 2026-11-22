"""All nineteen revisions, native entries, causal exits and annual data coverage."""

import numpy as np
import pandas as pd
import pytest

from backtest.annual_exit_engine import AnnualExitBacktestEngine
from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
from backtest.portfolio_engine import SharedPortfolioEngine
from scanner.annual_exit_policy import AFFECTED, EXIT_ONLY, REVIEW_ONLY, VERSION
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from scanner.multi_strategy_engine import MultiStrategyEngine
from scanner.strategy_registry import (
    REGISTRY_VERSION,
    get_strategy,
    historical_strategy_for_exit,
)
from services.execution_report import validate_result
from services.yearly_reference import YearlyReferenceCache
from tests.test_ema_pivot_scanners import signal_frame
from tests.test_vwma_yearly_research import history, pivot_frame

pytestmark = pytest.mark.usefixtures("annual_v10_policy")

LONGS = sorted(AFFECTED - EXIT_ONLY - REVIEW_ONLY)


def native_frame(key, mode="swing"):
    if key in EMA_PIVOT_SETUPS:
        frame = signal_frame(key, mode=mode)
        for column in pivot_frame().filter(like="FIB_YEAR_"):
            frame[column] = pivot_frame()[column].iloc[0]
        frame["VOL_SMA_20"] = 100.0
        return frame
    frame = pivot_frame().iloc[:2].copy()
    if mode == "intraday":
        frame.index = pd.date_range(
            "2026-03-02 10:00", periods=2, freq="15min", tz="Asia/Kolkata"
        )
    frame["EMA_9"], frame["EMA_20"], frame["EMA_50"] = [99, 104], [100, 103], [101, 102]
    frame["VWMA_9"], frame["VWMA_26"] = [99, 103], [100, 102]
    frame["RSI_14"] = 62.0
    return frame


def evaluate(key, frame, mode="swing"):
    return MultiStrategyEngine().evaluate(
        frame,
        mode=mode,
        interval="15m" if mode == "intraday" else "1d",
        strategy_ids=[key],
    )["evaluations"][0]


@pytest.mark.parametrize("key", sorted(AFFECTED))
def test_all_nineteen_have_same_exit_policy_and_no_automated_entry_approval(key):
    row = get_strategy(key)
    assert row["paper_eligible"] is False
    assert row["direction"] == "LONG"
    assert "FIB_YEAR_R3" in row["indicators"]
    assert "ATR" not in row["indicators"]
    assert "RSI below 30" in " ".join(row["stoploss_rules"])
    assert "support breach alone is not an exit" in " ".join(row["stoploss_rules"])
    assert "floor(initial_quantity/2)" in " ".join(row["target_rules"])
    if key in EXIT_ONLY:
        assert row["implementation_status"] == "exit_only"
        with pytest.raises(ValueError, match="exit-only"):
            MultiStrategyBacktestEngine().validate_strategy(key, mode=row["modes"][0])
    if key in REVIEW_ONLY:
        assert row["implementation_status"] == "review_required"
        with pytest.raises(ValueError, match="review"):
            MultiStrategyBacktestEngine().validate_strategy(key, mode=row["modes"][0])


@pytest.mark.parametrize("key", LONGS)
def test_native_long_entry_checks_arm_yearly_plan_without_atr(key):
    mode = "intraday" if key.startswith("tf_intraday") else "swing"
    frame = native_frame(key, mode)
    frame["ATR_WILDER_14"] = np.nan
    # Traditional pivot headroom no longer substitutes for annual sizing.
    frame["TRAD_WEEK_R1"] = 103.06
    row = evaluate(key, frame, mode)
    assert row["entry_state"] == "ARMED", row["failed_checks"]
    assert row["signal"] == "BUY"
    assert row["entry_plan"]["stop_is_resting_order"] is False
    assert row["entry_plan"]["partial_target"] == 110
    assert row["entry_plan"]["target2"] == 130
    assert row["entry_plan"]["stoploss"] == 90
    assert row["exit_policy_version"] == VERSION
    frame["FIB_YEAR_R1"] = np.nan
    assert evaluate(key, frame, mode)["entry_state"] == "WAIT"


@pytest.mark.parametrize("key", [k for k in EXIT_ONLY if k in EMA_PIVOT_SETUPS])
def test_bearish_pivot_setup_is_an_exit_without_short_plan_or_borrow(key):
    row = evaluate(key, native_frame(key))
    assert row["signal"] == "EXIT"
    assert row["exit_triggered"] is True
    assert row["entry_state"] == "EXIT_ONLY"
    assert row["risk"] == row["entry_plan"] == {}


@pytest.mark.parametrize(
    "key", ["tf_intraday_ema9_20_short", "tf_intraday_vwma9_26_short"]
)
def test_bearish_native_crossover_exits_long_and_never_opens_short(key):
    frame = native_frame(key, "intraday")
    frame["EMA_9"], frame["EMA_20"] = [102, 100], [101, 101]
    frame["VWMA_9"], frame["VWMA_26"] = [104, 103], [103, 104]
    frame["RSI_14"] = 38.0
    row = evaluate(key, frame, "intraday")
    assert row["signal"] == "EXIT"
    assert row["risk"] == {}
    assert evaluate(key, frame.assign(RSI_14=65), "intraday")["signal"] == "WAIT"


def simulate(frame, key="tf_swing_vwma9_26_rsi_volume", mode="swing", **kwargs):
    frame = frame.copy()
    frame["VWMA_9"], frame["VWMA_26"] = frame.VWMA_20, frame.VWMA_50
    frame.loc[frame.index[1], "VWMA_9"] = 103.0
    frame["RSI_14"] = 62.0
    return AnnualExitBacktestEngine().run(
        {"EXAMPLE": frame},
        strategy_id=key,
        mode=mode,
        interval="15m" if mode == "intraday" else "1d",
        cost_bps=12,
        slippage_bps=0,
        **kwargs,
    )


def test_shared_half_r1_and_r2_r3_trailing_reconcile_actual_cash_and_fees():
    result = simulate(pivot_frame())
    trade = result["trades"][0]
    assert trade["side"] == "LONG"
    assert [x["exit_reason"] for x in trade["exit_legs"]] == [
        "R1_PARTIAL_PROFIT",
        "R3_FINAL_TARGET",
    ]
    assert trade["exit_legs"][0]["quantity"] == trade["quantity"] // 2
    assert trade["initial_stoploss"] == 90
    assert trade["planned_initial_risk"] <= 500
    assert [x["reference"] for x in trade["stop_reference_history"]] == [110, 120]
    validate_result(
        {
            "status": "completed",
            "parameters": {
                "deployment_limit": 100000.0,
                "cash_reserve": 0.0,
                "max_positions": 3,
            },
            **result,
        }
    )
    assert result["metrics"]["net_profit"] == pytest.approx(trade["net_pnl"])


@pytest.mark.parametrize("group", ["neither", "A", "B"])
def test_only_complete_rule_groups_exit_and_fill_after_confirmation(group):
    frame = pivot_frame()
    frame.loc[frame.index[3:], ["open", "high", "low", "close"]] = [
        95.0,
        96.0,
        85.0,
        89.0,
    ]
    frame["volume"] = 500.0
    frame.loc[frame.index[1], "volume"] = 1200.0
    if group == "A":
        frame.loc[frame.index[3], "RSI_WILDER_14"] = 25.0
    elif group == "B":
        frame.loc[frame.index[3], "volume"] = 1200.0
    trade = simulate(frame)["trades"][0]
    if group == "neither":
        assert trade["exit_reason"] == "END_OF_TEST"
    else:
        assert trade["exit_at"] == frame.index[4].isoformat()
        assert trade["exit_reason"] == (
            "RSI_GAP_CLOSE_CONFIRMED_EXIT"
            if group == "A"
            else "SELLING_VOLUME_SUPPORT_EXIT"
        )


def test_r2_failure_exits_next_open_not_retroactively_at_r2():
    frame = pivot_frame()
    frame.loc[frame.index[4], "close"] = 119
    trade = simulate(frame)["trades"][0]
    assert trade["exit_reason"] == "R2_CLOSE_CONFIRMED_PROFIT"
    assert trade["exit_at"] == frame.index[5].isoformat()
    assert trade["final_exit_price"] == 122


def test_intraday_native_confirmation_and_1500_square_off():
    frame = pivot_frame()
    frame.index = pd.date_range(
        "2026-03-02 13:45", periods=7, freq="15min", tz="Asia/Kolkata"
    )
    frame.loc[:, ["open", "high", "low", "close"]] = [103, 105, 101, 104]
    result = simulate(frame, key="tf_intraday_vwma9_26_rsi_volume", mode="intraday")
    trade = result["trades"][0]
    assert trade["exit_reason"] == "INTRADAY_SQUARE_OFF"
    assert pd.Timestamp(trade["exit_at"]).strftime("%H:%M") == "15:00"
    assert trade["entry_at"] < trade["exit_at"]


def test_yearly_references_use_daily_history_and_cache_levels_not_intraday_extremes():
    daily = history()
    frame = native_frame("tf_intraday_vwma9_26_rsi_volume", "intraday")
    frame.index = pd.date_range(
        "2026-11-13 10:00", periods=2, freq="15min", tz="Asia/Kolkata"
    )
    calls = []

    class Market:
        def batch_candles_with_errors(self, symbols, **kwargs):
            calls.append((symbols, kwargs))
            return {"EXAMPLE": daily}, {}

    cache = YearlyReferenceCache()
    kwargs = dict(
        market_data=Market(),
        symbol="EXAMPLE",
        interval="15m",
        now="2026-11-15T17:00:00+05:30",
    )
    enriched = cache.enrich(frame, **kwargs)
    repeat = cache.enrich(frame.assign(high=9999), **kwargs)
    assert len(calls) == 1
    assert calls[0][1] == {"period": "5y", "interval": "1d"}
    pd.testing.assert_frame_equal(
        enriched.filter(like="FIB_YEAR_"), repeat.filter(like="FIB_YEAR_")
    )
    assert enriched.FIB_YEAR_P.notna().all()
    with pytest.raises(ValueError, match="one observed candle per session"):
        cache.enrich(
            frame,
            market_data=Market(),
            symbol="EXAMPLE",
            interval="1d",
            now=kwargs["now"],
        )


def test_public_portfolio_route_uses_shared_policy_and_legacy_lineage_is_retained():
    frame = pivot_frame()
    frame["VWMA_9"], frame["VWMA_26"], frame["RSI_14"] = (
        frame.VWMA_20,
        frame.VWMA_50,
        62.0,
    )
    frame.loc[frame.index[1], "VWMA_9"] = 103.0
    result = SharedPortfolioEngine().run(
        {"EXAMPLE": frame},
        strategy_id="tf_swing_vwma9_26_rsi_volume",
        mode="swing",
        interval="1d",
    )
    assert result["trades"][0]["exit_reason"] == "R3_FINAL_TARGET"
    assert (
        historical_strategy_for_exit("tf_intraday_ema9_20_short")["direction"]
        == "SHORT"
    )
    assert (
        "v15" in REGISTRY_VERSION
    )  # Current catalog version; replay fixture keeps v10 rules.
    assert len(AFFECTED) == 19 and len(EXIT_ONLY) == 9 and len(REVIEW_ONLY) == 2
    readiness = MultiStrategyBacktestEngine().readiness()
    assert not EXIT_ONLY.intersection(readiness["backtestable_strategy_ids"])


@pytest.mark.parametrize(
    "key",
    [
        "tf_intraday_vwap_breakdown_short",
        "tf_intraday_low20_breakdown_short",
        "tf_intraday_ema_adx_continuation_short",
    ],
)
def test_other_bearish_rules_emit_exit_without_atr_or_a_short_bracket(key):
    from tests.test_short_setups_execution import setup_frame

    frame = setup_frame(key).drop(columns="ATR")
    row = evaluate(key, frame, "intraday")
    assert row["signal"] == "EXIT", row["failed_checks"]
    assert row["risk"] == {} and row["paper_eligible"] is False
    stale = frame.iloc[-2:].copy()
    stale.index = pd.DatetimeIndex(
        [stale.index[0] - pd.Timedelta(days=1), stale.index[1]]
    )
    assert evaluate(key, stale, "intraday")["signal"] == "WAIT"
    frame["volume"] = 1.0
    assert evaluate(key, frame, "intraday")["signal"] == "WAIT"


@pytest.mark.parametrize("key", sorted(REVIEW_ONLY))
def test_undefined_entry_rules_remain_review_only_and_no_macd_filter_is_invented(key):
    row = get_strategy(key)
    mode = row["modes"][0]
    result = evaluate(key, pivot_frame(), mode)
    assert result["signal"] == "REVIEW_REQUIRED"
    assert result["risk"] == {}
    assert row["ambiguities"]


def service_fixture(tmp_path, *, intraday=False):
    from types import SimpleNamespace

    from core.database import initialize_database
    from database.repositories.backtest_results import BacktestResultsRepository
    from services.technical_trading_service import TechnicalTradingService

    raw = history()
    raw["volume"] = 1200.0
    raw.loc[:, ["open", "high", "low", "close"]] = [100, 120, 80, 100]
    raw.loc[raw.index.year == 2026, ["open", "high", "low", "close"]] = [
        102,
        104,
        101,
        103,
    ]
    native = pd.DataFrame(
        {"open": 102.0, "high": 104.0, "low": 101.0, "close": 103.0, "volume": 1200.0},
        index=pd.date_range(
            "2026-11-13 09:15", periods=25, freq="15min", tz="Asia/Kolkata"
        ),
    )
    calls = []

    def fetch(symbols, **kwargs):
        calls.append(kwargs)
        data = native if kwargs["interval"] == "15m" else raw
        return {symbol: data.copy() for symbol in symbols}, {}

    def indicators(frame):
        frame["VWMA_9"], frame["VWMA_26"] = 103.0, 102.0
        frame["RSI_14"], frame["RSI_WILDER_14"], frame["VOL_SMA_20"] = (
            62.0,
            60.0,
            1000.0,
        )
        # One synthetic native entry, with ample warm-up before execution.
        mask = frame.index < pd.Timestamp(
            "2026-11-13 10:00" if intraday else "2026-10-01", tz="Asia/Kolkata"
        )
        frame.loc[mask, "VWMA_9"] = 101.0
        return frame

    path = str(tmp_path / "shared-annual.db")
    initialize_database(path)
    service = TechnicalTradingService(
        market_data=SimpleNamespace(batch_candles_with_errors=fetch),
        indicator_engine=SimpleNamespace(calculate=indicators),
        repository=BacktestResultsRepository(db_path=path),
    )
    return service, calls


@pytest.mark.parametrize("intraday", [False, True])
def test_public_service_fetches_daily_references_uses_shared_engine_and_persists_report(
    tmp_path, intraday
):
    from services.portfolio_backtest_service import PortfolioBacktestService

    service, calls = service_fixture(tmp_path, intraday=intraday)
    mode = "intraday" if intraday else "swing"
    key = (
        "tf_intraday_vwma9_26_rsi_volume"
        if intraday
        else "tf_swing_vwma9_26_rsi_volume"
    )
    # Intraday scans/backtests still require 60 native bars.
    if intraday:
        original = service.market_data.batch_candles_with_errors

        def fetch(symbols, **kwargs):
            frames, failures = original(symbols, **kwargs)
            if kwargs["interval"] == "15m":
                for symbol, frame in frames.items():
                    previous = [
                        frame.set_axis(frame.index - pd.Timedelta(days=days))
                        for days in (4, 3, 2, 1)
                    ]
                    frames[symbol] = pd.concat([*previous, frame]).sort_index()
            return frames, failures

        service.market_data.batch_candles_with_errors = fetch
    result = PortfolioBacktestService(service).run(
        symbols=["EXAMPLE"],
        strategy_id=key,
        mode=mode,
        period="60d" if intraday else "2y",
        now=pd.Timestamp("2026-11-15T17:00:00+05:30"),
        cost_bps=12,
        slippage_bps=5,
        run_id="new-policy-report",
    )
    assert result["engine"] == {"name": "AnnualExitBacktestEngine", "version": VERSION}
    assert result["metrics"]["total_trades"] == 1
    assert result["parameters"]["price_only_stop_exit"] is False
    assert result["parameters"]["exit_confirmation_interval"] == (
        "15m" if intraday else "1d"
    )
    assert {"period": "5y", "interval": "1d"} in calls
    assert service.repository.by_run_id("new-policy-report")["result"]["report"]["rows"]
    assert all(t["side"] == "LONG" for t in result["trades"])
    if intraday:
        assert result["trades"][0]["exit_reason"] == "INTRADAY_SQUARE_OFF"
    service.repository.close()


@pytest.mark.parametrize("key", sorted(AFFECTED))
def test_revised_rules_cannot_enter_paper_even_with_a_claimed_passing_validation(key):
    from services.strategy_driven_paper_service import StrategyDrivenPaperService
    from tests.test_strategy_driven_paper_r72_5_4 import (
        SCAN_RUN_ID,
        VALIDATION_RUN_ID,
        FakeAutoEntry,
        FakeScanner,
        validation_status,
    )

    auto = FakeAutoEntry()
    service = StrategyDrivenPaperService(
        scanner_service=FakeScanner(), paper_auto_entry=auto
    )
    result = service.execute(
        strategy_id=key,
        scan_run_id=SCAN_RUN_ID,
        validation_run_id=VALIDATION_RUN_ID,
        validation_status=validation_status(),
    )
    assert result["status"] == "blocked"
    assert "registry_not_paper_eligible" in result["blockers"]
    assert auto.calls == []


@pytest.mark.parametrize("key", LONGS)
def test_each_long_strategy_fills_its_native_entry_and_uses_yearly_profit_legs(key):
    mode = "intraday" if key.startswith("tf_intraday") else "swing"
    pair = native_frame(key, mode)
    frame = pd.concat(
        [pair, *[pair.iloc[-1:].copy() for _ in range(4)]], ignore_index=True
    )
    frame.index = pd.date_range(
        "2026-03-02 10:00" if mode == "intraday" else "2026-03-02",
        periods=6,
        freq="15min" if mode == "intraday" else "B",
        tz="Asia/Kolkata",
    )
    for offset, prices in enumerate(
        [
            [103.1, 107.0, 102.0, 106.0],
            [107.0, 113.0, 106.0, 112.0],
            [112.0, 125.0, 111.0, 123.0],
            [123.0, 132.0, 122.0, 130.0],
        ],
        2,
    ):
        frame.loc[frame.index[offset], ["open", "high", "low", "close"]] = prices
    result = AnnualExitBacktestEngine().run(
        {"EXAMPLE": frame},
        strategy_id=key,
        mode=mode,
        interval="15m" if mode == "intraday" else "1d",
        cost_bps=12,
        slippage_bps=0,
    )
    trade = result["trades"][0]
    assert trade["entry_at"] == frame.index[2].isoformat()
    assert trade["initial_stoploss"] == 90.0
    assert [leg["exit_reason"] for leg in trade["exit_legs"]] == [
        "R1_PARTIAL_PROFIT",
        "R3_FINAL_TARGET",
    ]
    assert all(leg["side"] == "LONG" for leg in trade["exit_legs"])


def test_intraday_missing_square_off_bar_fails_without_overnight_fabrication():
    frame = pivot_frame()
    frame.index = pd.DatetimeIndex(
        [
            "2026-03-02 13:45",
            "2026-03-02 14:00",
            "2026-03-02 14:15",
            "2026-03-02 14:30",
            "2026-03-02 14:45",
            "2026-03-02 15:15",
            "2026-03-03 09:15",
        ],
        tz="Asia/Kolkata",
    )
    with pytest.raises(ValueError, match="square-off candle"):
        simulate(frame, key="tf_intraday_vwma9_26_rsi_volume", mode="intraday")
