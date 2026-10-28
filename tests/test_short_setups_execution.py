"""Short rules, SQLite paper fills and failure explanations; no broker writes."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from test_intraday_shorts import NOW, SHORTS, book, candles
from test_saved_strategy_automation import build

from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
from database.repositories.strategy_runtime_state_repository import (
    StrategyRuntimeStateRepository,
)
from indicators.price_action import PriceAction
from indicators.volume import VolumeIndicators
from providers.kite_paper_quotes import FreshKitePaperQuotes
from scanner.multi_strategy_engine import MultiStrategyEngine
from scanner.strategy_registry import REGISTRY_VERSION, get_strategy, list_strategies
from services.kite_trading_readiness import kite_trading_readiness
from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner
from services.paper_auto_entry_service import PaperAutoEntryService
from services.paper_trading_service import PaperTradingService
from services.strategy_driven_paper_service import StrategyDrivenPaperService
from services.strategy_paper_automation import StrategyPaperAutomation
from webapp.market_colours import GREEN, RED, market_frame, signal_colour, signed_colour

NEW_SHORTS = [
    "tf_intraday_vwap_breakdown_short",
    "tf_intraday_low20_breakdown_short",
    "tf_intraday_ema_adx_continuation_short",
]


def setup_frame(strategy_id):
    frame = candles()
    if strategy_id in SHORTS:
        return frame
    frame["EMA_9"] = 100.2
    frame["EMA_20"] = 101.0
    frame["EMA_50"] = 102.0
    frame["ADX"] = 25.0
    frame["+DI"] = 10.0
    frame["-DI"] = 30.0
    frame["VWAP_SESSION"] = 100.5
    frame["LOW_20_PREV"] = 100.5
    previous = frame.index[-2]
    frame.loc[previous, ["open", "high", "low", "close"]] = [101, 102, 100.5, 101]
    return frame


@pytest.mark.parametrize("strategy_id", NEW_SHORTS)
def test_new_rules_require_bearish_confirmation_and_correct_risk(strategy_id):
    engine = MultiStrategyEngine()
    frame = setup_frame(strategy_id)
    row = engine.evaluate(
        frame, mode="intraday", interval="15m", strategy_ids=[strategy_id]
    )["evaluations"][0]
    assert row["signal"] == "SELL" and row["score"] == 100
    assert row["risk"] == {
        "entry": 100,
        "stoploss": 103,
        "target2": 94,
        "reward_risk": 2,
    }
    assert get_strategy(strategy_id)["direction"] == "SHORT"
    frame.loc[frame.index[-1], "RSI_14"] = 65
    assert (
        engine.evaluate(
            frame, mode="intraday", interval="15m", strategy_ids=[strategy_id]
        )["evaluations"][0]["signal"]
        == "EXIT"
    )
    assert (
        engine.evaluate_exit(
            frame, mode="intraday", interval="15m", strategy_ids=[strategy_id]
        )["evaluations"][0]["signal"]
        == "EXIT"
    )


@pytest.mark.parametrize("strategy_id", NEW_SHORTS)
@pytest.mark.parametrize(
    "damage", ["volume", "nan", "bad_atr", "overnight_pair", "after_cutoff"]
)
def test_no_forced_sell_from_incomplete_or_invalid_conditions(strategy_id, damage):
    frame = setup_frame(strategy_id)
    if damage == "volume":
        frame.loc[frame.index[-1], "volume"] = 100
    elif damage == "nan":
        frame.loc[frame.index[-1], get_strategy(strategy_id)["indicators"][0]] = float(
            "nan"
        )
    elif damage == "bad_atr":
        frame.loc[frame.index[-1], "ATR"] = 100
    elif damage == "overnight_pair":
        frame = frame.iloc[-2:].copy()
        frame.index = pd.DatetimeIndex(
            [NOW - timedelta(days=1), NOW - timedelta(minutes=15)]
        )
    else:
        frame.index = frame.index[:-1].append(
            pd.DatetimeIndex([NOW.replace(hour=14, minute=45)])
        )
    row = MultiStrategyEngine().evaluate(
        frame, mode="intraday", interval="15m", strategy_ids=[strategy_id]
    )["evaluations"][0]
    assert row["signal"] != "SELL"


def test_session_vwap_resets_in_ist_and_prior_low_excludes_the_signal_bar():
    frame = pd.DataFrame(
        {
            "high": [100, 200, 202],
            "low": [100, 200, 202],
            "close": [100, 200, 202],
            "volume": [1000, 10, 10],
        },
        index=pd.to_datetime(
            ["2026-10-27T09:45:00Z", "2026-10-28T03:45:00Z", "2026-10-28T04:00:00Z"]
        ),
    )
    result = VolumeIndicators.add_vwap(frame.copy())
    assert result["VWAP_SESSION"].tolist() == [100, 200, 201]
    assert result["VWAP"].iloc[-1] < 110  # Legacy lookback value is not reused.
    raw = candles().iloc[:25].copy()
    raw.loc[raw.index[-1], "low"] = 1
    result = PriceAction.add_breakdown(raw)
    assert result["LOW_20_PREV"].iloc[-1] == 99
    assert pd.isna(result["LOW_20_PREV"].iloc[19])


@pytest.mark.parametrize("strategy_id", [*SHORTS, *NEW_SHORTS])
@pytest.mark.parametrize("cover_price,reason", [(94, "TARGET"), (104, "STOPLOSS")])
def test_actual_scanner_automation_paper_fill_and_cover_persist_in_sqlite(
    tmp_path, monkeypatch, strategy_id, cover_price, reason
):
    runtime = book(tmp_path, monkeypatch)
    monkeypatch.setenv(
        "TRENDFORGE_MULTI_STRATEGY_RESULTS_PATH", str(tmp_path / "scanner.json")
    )
    monkeypatch.setenv("TRENDFORGE_PAPER_MAX_OPEN_POSITIONS", "3")
    state = StrategyRuntimeStateRepository()
    paper = PaperTradingService(runtime, enabled=True, environment_kill_switch=False)
    # Isolated test fixture supplies verified storage evidence. Production code
    # continues to require the PC/cloud restart-verification contract.
    monkeypatch.setattr(
        paper,
        "entry_storage_policy",
        lambda: {
            "mode": "durable",
            "verified_persistent": True,
            "entry_allowed": True,
        },
    )
    frame = setup_frame(strategy_id)
    scanner = MultiStrategyNiftyScanner(
        market_data=SimpleNamespace(
            batch_candles_with_errors=lambda *a, **k: ({"TCS": frame.copy()}, {})
        ),
        indicator_engine=SimpleNamespace(calculate=lambda f: f),
        universe_provider=SimpleNamespace(
            load=lambda *a, **k: {"members": [{"symbol": "TCS"}], "count": 1}
        ),
        state_repository=state,
    )
    auto = PaperAutoEntryService(paper, enabled=True)
    bridge = StrategyDrivenPaperService(
        scanner_service=scanner, paper_auto_entry=auto, state_repository=state
    )
    quotes = FreshKitePaperQuotes(
        SimpleNamespace(
            quote=lambda instruments: {
                instrument: {"last_price": 100, "timestamp": NOW}
                for instrument in instruments
            }
        )
    )
    validation = {
        "status": "completed",
        "run_id": "controlled-validation",
        "registry_version": REGISTRY_VERSION,
        "request": {
            "universes": ["NIFTY 500"],
            "source": "all",
            "modes": ["intraday", "swing", "positional"],
        },
        "strategy_validation": [
            {
                "strategy_id": strategy_id,
                "mode": "intraday",
                "promotion_status": "ELIGIBLE_FOR_REVIEW",
                "registry_paper_eligible": True,
                "universe_gates": [{"universe": "NIFTY 500", "status": "PASS"}],
            }
        ],
    }
    service = StrategyPaperAutomation(
        scanner=scanner,
        bridge=bridge,
        repository=state,
        quote_provider=quotes,
        paper_monitor=SimpleNamespace(tick=lambda **k: None),
        strategy_monitor=SimpleNamespace(tick=lambda **k: None),
        validation_getter=lambda: validation,
        validation_starter=lambda **k: None,
        clock=lambda: NOW,
    )
    try:
        service.configure(
            True, universe="NIFTY 500", symbols=["TCS"], strategy_ids=[strategy_id]
        )
        cycle = service.tick()
        assert cycle["opened_count"] == 1, cycle
        assert cycle["entry_status"] == "opened"
        outcome = cycle["strategies"][0]
        assert (
            outcome["scanner_matches"]
            == outcome["candidate_count"]
            == outcome["risk_approved_count"]
            == 1
        )
        position = runtime.snapshot()["positions"][0]
        assert position["side"] == "SHORT" and position["strategy_id"] == strategy_id
        assert position["source_scan_run_id"].startswith("auto:intraday:")
        service.tick()
        assert len(runtime.snapshot()["positions"]) == 1
        assert service.status()["last_cycle"] == {
            key: value for key, value in cycle.items() if key != "status"
        }
        closed = paper.monitor({"TCS": cover_price}, now=NOW + timedelta(minutes=1))[
            "closed"
        ][0]
        assert (closed["pnl"] > 0) is (reason == "TARGET")
        assert closed["reason"] == reason
        assert runtime.trades.get(closed["trade_id"])["pnl"] == closed["pnl"]
    finally:
        runtime.close()
        state.close()


@pytest.mark.parametrize("strategy_id", NEW_SHORTS)
def test_new_rule_backtests_cover_shorts_and_charge_costs(strategy_id):
    frame = setup_frame(strategy_id)
    rest = frame.iloc[[-1]].copy()
    tail = pd.concat([rest] * 21)
    tail.index = pd.date_range(
        "2026-10-28 10:00", "2026-10-28 15:00", freq="15min", tz="Asia/Kolkata"
    )
    tail.loc[tail.index[1], "low"] = 93
    result = MultiStrategyBacktestEngine().run(
        pd.concat([frame, tail]),
        strategy_id=strategy_id,
        mode="intraday",
        interval="15m",
        cost_bps=12,
        slippage_bps=5,
    )
    assert result.trades
    assert result.trades[-1]["side"] == "SHORT"
    assert result.trades[-1]["transaction_costs"] > 0


def test_idle_polls_preserve_actual_rejection_evidence():
    env = build()
    env.service.bridge.execute = lambda **k: {
        "status": "risk_blocked",
        "candidate_count": 1,
        "r67_2_approved_count": 0,
        "candidates": [
            {"r67_2_approved": False, "r67_2_reasons": ["minimum_rr_not_met"]}
        ],
    }
    env.service.configure(True)
    env.service.tick()
    cycle = deepcopy(env.service.status()["last_cycle"])
    assert cycle["strategies"][0]["rejections"] == [["minimum_rr_not_met"]]
    assert cycle["entry_status"] == "blocked"
    env.service.tick()
    assert env.service.status()["last_cycle"] == cycle


def test_no_signal_cycle_is_distinct_from_review_only_catalog_rows():
    env = build()
    env.service.bridge.execute = lambda **k: {
        "status": "no_candidates",
        "candidate_count": 0,
    }
    env.service.configure(True)
    assert env.service.tick()["entry_status"] == "no_entry_signals"


def test_catalog_contains_five_short_rules_and_colours_preserve_values():
    assert len([r for r in list_strategies() if r["direction"] == "SHORT"]) == 5
    assert GREEN in signed_colour(50) and RED in signed_colour(-50)
    assert RED in signal_colour("SELL") and GREEN in signal_colour("BUY")
    assert RED not in signed_colour(float("nan"))
    frame = pd.DataFrame({"signal": ["SELL", "WAIT"], "net_pnl": [50, -30]})
    pd.testing.assert_frame_equal(market_frame(frame).data, frame)


def test_history_probe_separates_working_auth_from_denied_candle_access():
    class Broker:
        def health(self):
            return {"authenticated": True}

        def candles(self, *args, **kwargs):
            raise RuntimeError("PRIVATE credentials must not appear in diagnostics")

    report = kite_trading_readiness(Broker(), probe_history=True, now=NOW)
    assert report["authenticated"] is True
    assert report["history_status"] == "unavailable_or_invalid"
    assert report["broker_orders_allowed"] is False
    assert report["orders_submitted"] == 0
    assert "PRIVATE" not in str(report)


def test_history_probe_normalizes_kite_columns_and_calculates_scanner_indicators():
    import numpy as np

    frame = candles()[["open", "high", "low", "close", "volume"]].copy()
    close = 100 + np.sin(np.arange(len(frame))) + np.arange(len(frame)) * 0.02
    frame["close"] = close
    frame["open"] = close - 0.05
    frame["high"] = close + 1
    frame["low"] = close - 1
    broker = SimpleNamespace(
        health=lambda: {"authenticated": True},
        candles=lambda *a, **k: frame.rename(columns=str.title),
    )
    report = kite_trading_readiness(broker, probe_history=True, now=NOW)
    assert report["history_status"] == "available", report
    assert report["indicator_status"] == "calculated"
    assert report["history_completed_candles"] == len(frame)
    assert report["orders_submitted"] == 0
