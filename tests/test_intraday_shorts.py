"""Directional scanner, shared-cash simulation and durable paper contracts."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
from backtest.portfolio_engine import SharedPortfolioEngine
from core.database import initialize_database
from database.repositories.trade_repository import TradeRepository
from scanner.multi_strategy_engine import MultiStrategyEngine
from scanner.portfolio_policy import allocate_candidates, evidence_rows, risk_details
from scanner.strategy_registry import REGISTRY_VERSION, get_strategy
from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner
from services.paper_auto_entry_service import PaperAutoEntryService
from services.paper_trading_runtime import PaperTradingRuntime
from services.strategy_driven_paper_service import StrategyDrivenPaperService
from services.technical_trading_service import TechnicalTradingService

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 28, 10, 0, tzinfo=TZ)
SHORTS = ["tf_intraday_ema9_20_short", "tf_intraday_vwma9_26_short"]


def candles():
    dates = pd.bdate_range("2026-10-21", "2026-10-28")
    stamps = [
        stamp
        for day in dates
        for stamp in pd.date_range(
            day.strftime("%Y-%m-%d") + " 09:15",
            periods=3 if day.day == 28 else 25,
            freq="15min",
            tz=TZ,
        )
    ]
    frame = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 2000.0,
            "VOL_SMA_20": 1000.0,
            "ATR": 2.0,
            "RSI_14": 35.0,
            "EMA_9": 100.5,
            "EMA_20": 100.0,
            "VWMA_9": 100.5,
            "VWMA_26": 100.0,
        },
        index=pd.DatetimeIndex(stamps),
    )
    frame.loc[frame.index[-1], ["EMA_9", "VWMA_9"]] = 99.5
    return frame


@pytest.mark.parametrize("strategy_id", SHORTS)
def test_actual_short_rules_and_positive_directional_brackets(strategy_id):
    result = MultiStrategyEngine().evaluate(
        candles(), mode="intraday", interval="15m", strategy_ids=[strategy_id]
    )
    row = result["evaluations"][0]
    assert row["signal"] == "SELL" and row["score"] == 100
    assert result["consensus"] == "SELL" and result["sell_strategy_ids"] == [
        strategy_id
    ]
    assert row["risk"]["stoploss"] == 103 and row["risk"]["target2"] == 94
    assert risk_details(100, 103, 94, side="SHORT")["risk_reward"] == "1:2.00"
    assert get_strategy(strategy_id)["source"] == "user_analysis"


@pytest.mark.parametrize("damage", ["rsi", "volume", "crossover", "time", "atr"])
def test_incomplete_or_invalid_short_setup_never_becomes_entry(damage):
    frame = candles()
    key, value = {
        "rsi": ("RSI_14", float("nan")),
        "volume": ("volume", 100),
        "crossover": ("EMA_9", 100.5),
        "atr": ("ATR", 100),
    }.get(damage, ("ATR", 2))
    frame.loc[frame.index[-1], key] = value
    if damage == "time":
        frame.index = frame.index[:-1].append(
            pd.DatetimeIndex([NOW.replace(hour=9, minute=30)])
        )
    row = MultiStrategyEngine().evaluate(
        frame, mode="intraday", interval="15m", strategy_ids=[SHORTS[0]]
    )["evaluations"][0]
    assert row["signal"] != "HOLD"
    assert not allocate_candidates(
        [{"symbol": "TCS", **row, **row["risk"]}], budget=80000, slots=3
    )


def test_hold_is_only_emitted_by_existing_position_exit_evaluation():
    frame = candles()
    frame["EMA_9"] = 100.5
    frame["RSI_14"] = 50
    engine = MultiStrategyEngine()
    assert (
        engine.evaluate(
            frame, mode="intraday", interval="15m", strategy_ids=[SHORTS[0]]
        )["evaluations"][0]["signal"]
        == "WAIT"
    )
    assert (
        engine.evaluate_exit(
            frame, mode="intraday", interval="15m", strategy_ids=[SHORTS[0]]
        )["evaluations"][0]["signal"]
        == "HOLD"
    )
    frame.loc[frame.index[-1], "RSI_14"] = 65
    assert (
        engine.evaluate_exit(
            frame, mode="intraday", interval="15m", strategy_ids=[SHORTS[0]]
        )["evaluations"][0]["signal"]
        == "EXIT"
    )
    assert evidence_rows([{"symbol": "TCS", "signal": "HOLD"}])[0]["signal"] == "WAIT"


def test_short_workspace_and_full_universe_scanner_preserve_sell_lineage(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "TRENDFORGE_MULTI_STRATEGY_RESULTS_PATH", str(tmp_path / "scanner.json")
    )
    frame = candles()
    market = SimpleNamespace(
        batch_candles_with_errors=lambda *args, **kwargs: ({"TCS": frame}, {})
    )
    indicators = SimpleNamespace(calculate=lambda f: f)
    service = TechnicalTradingService(
        market_data=market, indicator_engine=indicators, repository=SimpleNamespace()
    )
    scan = service.scan(
        symbols=["TCS"], mode="intraday", strategy_id=SHORTS[0], now=NOW
    )
    assert scan["sell_candidates"] == 1 and scan["buy_candidates"] == 0
    assert (
        scan["results"][0]["side"] == "SHORT"
        and scan["top_picks"][0]["execution_eligible"]
    )
    universe = SimpleNamespace(
        load=lambda *args, **kwargs: {"members": [{"symbol": "TCS"}]}
    )
    scanner = MultiStrategyNiftyScanner(
        market_data=market, indicator_engine=indicators, universe_provider=universe
    )
    full = scanner.scan(mode="intraday", strategy_ids=SHORTS, now=NOW)
    assert (
        full["status"] == "completed"
        and full["top_picks"][0]["consensus"] == "STRONG_SELL"
    )
    assert all(
        row["signal"] == "SELL" for row in full["top_picks"][0]["strategy_evaluations"]
    )


class Decisions:
    def readiness(self):
        return {"executable_strategy_ids": SHORTS}

    def evaluate(self, frame, **kwargs):
        current = frame.iloc[-1]
        return {
            "evaluations": [
                {
                    "status": "evaluated",
                    "signal": current["directive"],
                    "score": current["test_score"],
                    "risk": {
                        "entry": 100,
                        "stoploss": 104,
                        "target2": 92,
                        "reward_risk": 2,
                    },
                    "checks": {"fixture": True},
                }
            ]
        }


def history(score=100):
    frame = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "directive": "WAIT",
            "test_score": score,
        },
        index=pd.date_range(
            "2026-10-28 09:30", "2026-10-28 15:00", freq="15min", tz=TZ
        ),
    )
    frame.iloc[1, frame.columns.get_loc("directive")] = "SELL"
    return frame


@pytest.mark.parametrize(
    "exit_kind,price,reason",
    [
        ("target", 92, "ATR_TARGET"),
        ("stop", 104, "ATR_STOP"),
        ("both", 104, "ATR_STOP"),
        ("gap", 110, "ATR_STOP"),
        ("session", 100, "INTRADAY_SESSION_EXIT_1500"),
    ],
)
def test_short_shared_portfolio_fills_covering_pnl_costs_and_collateral(
    exit_kind, price, reason
):
    frames = {
        symbol: history(score)
        for symbol, score in zip("ABCD", [90, 60, 30, 10], strict=True)
    }
    for frame in frames.values():
        stamp = frame.index[3]
        if exit_kind in {"target", "both"}:
            frame.loc[stamp, "low"] = 90
        if exit_kind in {"stop", "both"}:
            frame.loc[stamp, "high"] = 105
        if exit_kind == "gap":
            frame.loc[stamp, ["open", "high", "low", "close"]] = [110, 111, 109, 110]
    result = SharedPortfolioEngine(strategy_engine=Decisions()).run(
        frames,
        strategy_id=SHORTS[0],
        mode="intraday",
        interval="15m",
        cost_bps=0,
        slippage_bps=0,
    )
    assert {t["symbol"] for t in result["trades"]} == set("ABC")
    assert [a["allocation_budget"] for a in result["allocations"]] == pytest.approx(
        [40000, 80000 / 3, 80000 / 6]
    )
    for trade in result["trades"]:
        assert trade["side"] == "SHORT" and trade["exit_reason"] == reason
        assert trade["exit_price"] == price
        assert trade["net_pnl"] == pytest.approx((100 - price) * trade["quantity"])
        assert pd.Timestamp(trade["entry_at"]) > pd.Timestamp(trade["entry_signal_at"])
    assert result["metrics"]["minimum_cash"] >= 20000
    assert result["metrics"]["max_capital_committed"] <= 80000
    assert sum(t["net_pnl"] for t in result["trades"]) == pytest.approx(
        result["metrics"]["net_profit"], abs=0.04
    )
    with_costs = SharedPortfolioEngine(strategy_engine=Decisions()).run(
        frames,
        strategy_id=SHORTS[0],
        mode="intraday",
        interval="15m",
        cost_bps=12,
        slippage_bps=5,
    )
    assert with_costs["metrics"]["net_profit"] < result["metrics"]["net_profit"]
    assert all(t["entry_price"] < 100 for t in with_costs["trades"])


def test_validation_backtest_short_direction_and_no_overnight():
    frame = history()
    frame.loc[frame.index[3], "low"] = 91
    result = MultiStrategyBacktestEngine(strategy_engine=Decisions()).run(
        frame,
        strategy_id=SHORTS[0],
        mode="intraday",
        interval="15m",
        cost_bps=12,
        slippage_bps=5,
    )
    assert result.trades[0]["side"] == "SHORT" and result.trades[0]["net_pnl"] > 0
    assert result.trades[0]["transaction_costs"] > 0
    with pytest.raises(ValueError):
        MultiStrategyBacktestEngine().run(
            frame, strategy_id=SHORTS[0], mode="swing", interval="1d"
        )
    frame = history().iloc[:-1]
    tomorrow = frame.iloc[[-1]].copy()
    tomorrow.index = pd.DatetimeIndex([NOW + timedelta(days=1)])
    with pytest.raises(ValueError, match="square-off"):
        MultiStrategyBacktestEngine(strategy_engine=Decisions()).run(
            pd.concat([frame, tomorrow]),
            strategy_id=SHORTS[0],
            mode="intraday",
            interval="15m",
        )


def book(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "paper.db"))
    initialize_database()
    return PaperTradingRuntime(trades=TradeRepository())


def order(**kwargs):
    return SimpleNamespace(
        **{
            "symbol": "TCS",
            "side": "SHORT",
            "quantity": 10,
            "price": 100,
            "stoploss": 104,
            "target2": 92,
            "trade_mode": "intraday",
            "strategy_id": SHORTS[0],
            "entry_signal": "SELL",
            **kwargs,
        }
    )


@pytest.mark.parametrize(
    "quote,pnl,reason", [(92, 80, "TARGET"), (105, -50, "STOPLOSS")]
)
def test_short_paper_restore_and_cover_reconcile_to_durable_ledger(
    tmp_path, monkeypatch, quote, pnl, reason
):
    runtime = book(tmp_path, monkeypatch)
    trade_id = runtime.open(order(), now=NOW)
    assert runtime.snapshot()["positions"][0]["signal"] == "HOLD"
    runtime.close()
    restored = PaperTradingRuntime(trades=TradeRepository())
    assert restored.restore_open() == 1
    closed = restored.monitor({"TCS": quote}, now=NOW + timedelta(minutes=1))
    assert closed[0]["reason"] == reason and closed[0]["pnl"] == pnl
    assert restored.trades.get(trade_id)["pnl"] == pnl
    assert restored.snapshot()["realized_pnl"] == pnl
    restored.close()


def test_short_paper_square_off_and_missed_session_recovery(tmp_path, monkeypatch):
    runtime = book(tmp_path, monkeypatch)
    runtime.open(order(), now=NOW)
    assert (
        runtime.monitor({"TCS": 99}, now=NOW.replace(hour=15))[0]["reason"]
        == "FORCE_EXIT_15_00_IST"
    )
    runtime.open(order(symbol="INFY"), now=NOW)
    assert (
        runtime.monitor({"INFY": 99}, now=NOW + timedelta(days=1))[0]["reason"]
        == "MISSED_INTRADAY_SQUARE_OFF"
    )
    for changed in [
        {"trade_mode": "swing"},
        {"stoploss": 95},
        {"target2": 105},
        {"side": "INVALID"},
    ]:
        with pytest.raises(ValueError):
            runtime.open(order(symbol="BAD", **changed), now=NOW)
    runtime.close()


def test_short_paper_auto_entry_requires_registered_intraday_rule_and_correct_side(
    tmp_path, monkeypatch
):
    runtime = book(tmp_path, monkeypatch)
    paper = SimpleNamespace(
        runtime=runtime,
        can_open_new_positions=True,
        open=lambda order, **kwargs: {"trade_id": runtime.open(order, **kwargs)},
    )
    auto = PaperAutoEntryService(paper, enabled=True)
    strategy = get_strategy(SHORTS[0])
    candidate = StrategyDrivenPaperService._adapt_candidate(
        candidate={"symbol": "TCS", "bar_at": NOW.isoformat(), "consensus_score": 80},
        evaluation={
            "score": 100,
            "risk": {"entry": 100, "stoploss": 104, "target2": 92},
        },
        strategy_id=SHORTS[0],
        strategy=strategy,
        mode="intraday",
        scan_run_id="scan",
        validation_run_id="validation",
    )
    assert auto.evaluate_candidate(candidate, now=NOW)["approved"]
    for change in [
        {"technical_mode": "swing"},
        {"strategy_id": "tf_intraday_ema9_20_momentum"},
    ]:
        assert not auto.evaluate_candidate({**candidate, **change}, now=NOW)["approved"]
    assert not auto.evaluate_candidate(
        {**candidate, "signal": {**candidate["signal"], "signal": "WAIT"}}, now=NOW
    )["approved"]
    result = auto.process_scan(
        {"outcome": "completed", "top_picks": [candidate]},
        run_id="scan",
        execute_requested=True,
        now=NOW,
    )
    assert result["opened"][0]["side"] == "SHORT"
    assert runtime.snapshot()["positions"][0]["side"] == "SHORT"
    assert result["broker_orders_allowed"] is False
    runtime.close()


def test_stale_catalog_validation_is_not_reused_for_new_short_entries():
    from test_saved_strategy_automation import build

    env = build()
    env.validation["registry_version"] = "source-six-v1"
    env.service.configure(True)
    assert env.service.tick()["status"] == "validating_strategies"
    assert env.validations == [True] and not env.scans
    env.validation["registry_version"] = REGISTRY_VERSION
    env.service.tick()
    assert env.scans


def test_long_and_short_entries_share_capital_and_losses_reduce_buying_power(
    tmp_path, monkeypatch
):
    runtime = book(tmp_path, monkeypatch)
    for symbol in "ABCD":
        runtime.open(
            order(
                symbol=symbol,
                side="BUY",
                quantity=200,
                stoploss=96,
                target2=108,
                strategy_id="tf_intraday_ema9_20_momentum",
            ),
            now=NOW,
        )
    paper = SimpleNamespace(runtime=runtime, can_open_new_positions=True)
    auto = PaperAutoEntryService(paper, enabled=True)
    candidate = {
        "symbol": "TCS",
        "execution_eligible": True,
        "technical_mode": "intraday",
        "strategy_id": SHORTS[0],
        "signal": {
            "signal": "SELL",
            "overall_score": 100,
            "confidence": 80,
            "entry": 100,
            "stoploss": 104,
            "target2": 92,
        },
    }
    gate = auto.evaluate_candidate(candidate, now=NOW)
    assert not gate["approved"] and gate["remaining_entry_capital"] == 0
    runtime.close_strategy_exit("A", 95, exit_signal="EXIT", now=NOW)
    gate = auto.evaluate_candidate(candidate, now=NOW)
    assert gate["approved"] and gate["remaining_entry_capital"] == 19000
    assert gate["quantity"] == 190
    runtime.close()


def test_withdrawn_admission_cannot_open_a_short(tmp_path, monkeypatch):
    runtime = book(tmp_path, monkeypatch)
    calls = []
    paper = SimpleNamespace(
        runtime=runtime,
        can_open_new_positions=True,
        open=lambda *args, **kwargs: calls.append(True),
    )
    auto = PaperAutoEntryService(paper, enabled=True)
    candidate = {
        "symbol": "TCS",
        "execution_eligible": True,
        "technical_mode": "intraday",
        "strategy_id": SHORTS[0],
        "signal": {
            "signal": "SELL",
            "overall_score": 100,
            "confidence": 80,
            "entry": 100,
            "stoploss": 104,
            "target2": 92,
        },
    }
    result = auto.process_scan(
        {"outcome": "completed", "top_picks": [candidate]},
        run_id="short-stop",
        execute_requested=True,
        now=NOW,
        admission_guard=lambda candidate: False,
    )
    assert result["opened"] == [] and not calls
    assert runtime.snapshot()["open_positions"] == 0
    runtime.close()
