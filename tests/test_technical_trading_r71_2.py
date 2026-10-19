from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from scanner.technical_strategy import (
    latest_signal,
    strategy_profile,
)
from services.technical_trading_service import TechnicalTradingService


def _frame(mode: str, rows: int = 70) -> pd.DataFrame:
    if mode == "intraday":
        index = pd.date_range(
            "2026-10-16 09:15",
            periods=rows,
            freq="15min",
            tz="Asia/Kolkata",
        )
    else:
        index = pd.date_range(
            "2026-01-01",
            periods=rows,
            freq="D",
            tz="Asia/Kolkata",
        )

    data = pd.DataFrame(
        {
            "open": [100.0] * rows,
            "high": [102.0] * rows,
            "low": [99.0] * rows,
            "close": [101.0] * rows,
            "volume": [2000.0] * rows,
            "EMA_9": [101.0] * rows,
            "EMA_20": [100.0] * rows,
            "EMA_50": [95.0] * rows,
            "EMA_100": [90.0] * rows,
            "EMA_200": [85.0] * rows,
            "VWMA_9": [101.0] * rows,
            "VWMA_26": [99.0] * rows,
            "VWAP": [100.0] * rows,
            "RSI": [62.0] * rows,
            "MACD": [1.0] * rows,
            "MACD_SIGNAL": [0.5] * rows,
            "MACD_HIST": [0.5] * rows,
            "ADX": [28.0] * rows,
            "+DI": [30.0] * rows,
            "-DI": [15.0] * rows,
            "ATR": [2.0] * rows,
            "RVOL": [1.5] * rows,
            "BREAKOUT": [False] * rows,
        },
        index=index,
    )

    if mode == "intraday":
        data.iloc[-2, data.columns.get_loc("EMA_9")] = 99.0
        data.iloc[-2, data.columns.get_loc("EMA_20")] = 100.0
    else:
        data.iloc[-2, data.columns.get_loc("EMA_20")] = 99.0
        data.iloc[-2, data.columns.get_loc("EMA_50")] = 100.0
        data.iloc[-1, data.columns.get_loc("EMA_20")] = 101.0
        data.iloc[-1, data.columns.get_loc("EMA_50")] = 100.0
    return data


class FakeIndicators:
    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        return frame.copy()


class FakeMarketData:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames
        self.calls = []

    def begin_observation(self):
        return None

    def candles(self, symbol, period="1y", interval="1d"):
        self.calls.append((symbol, period, interval))
        return self.frames[symbol].copy()

    def batch_candles_with_errors(self, symbols, period="1y", interval="1d"):
        self.calls.append((tuple(symbols), period, interval))
        return (
            {
                symbol: self.frames[symbol].copy()
                for symbol in symbols
                if symbol in self.frames
            },
            {
                symbol: "missing"
                for symbol in symbols
                if symbol not in self.frames
            },
        )

    def observability_snapshot(self, symbols=None):
        return {
            "provider_counts": {"KiteProvider": len(symbols or [])},
            "fallback_count": 0,
        }

    def health(self):
        return {
            "status": "healthy",
            "provider": "RoutedMarketDataProvider",
            "provider_health": {
                "providers": ["KiteProvider"],
                "fallback_on_error": False,
            },
        }


class FakePaperAutoEntry:
    def __init__(self):
        self.calls = []

    def health(self):
        return {
            "status": "ready",
            "paper_only": True,
            "broker_orders_allowed": False,
        }

    def process_scan(
        self,
        scan_result,
        *,
        run_id,
        execute_requested,
        continuation=False,
        now=None,
    ):
        self.calls.append(
            {
                "scan_result": scan_result,
                "run_id": run_id,
                "execute_requested": execute_requested,
                "continuation": continuation,
            }
        )
        return {
            "status": "executed" if execute_requested else "not_requested",
            "opened": (
                [{"symbol": scan_result["top_picks"][0]["symbol"]}]
                if execute_requested and scan_result["top_picks"]
                else []
            ),
            "broker_orders_allowed": False,
        }


class FakeRepository:
    def __init__(self):
        self.rows = {}

    def by_run_id(self, run_id):
        return self.rows.get(run_id)

    def save(self, row):
        self.rows[row["run_id"]] = dict(row)

    def close(self):
        return None


def test_intraday_profile_emits_fresh_buy_with_exposed_evidence():
    frame = _frame("intraday")
    signal = latest_signal(frame, strategy_profile("intraday"))

    assert signal["signal"] == "BUY"
    assert signal["score"] >= 75.0
    assert signal["trigger"] == "EMA9_CROSS_ABOVE_EMA20"
    assert signal["risk"]["stoploss"] < signal["risk"]["entry"]
    assert signal["risk"]["target2"] > signal["risk"]["entry"]
    assert signal["evidence"]["close_above_vwap"] is True


def test_swing_profile_emits_ema20_50_cross_buy():
    frame = _frame("swing")
    signal = latest_signal(frame, strategy_profile("swing"))

    assert signal["signal"] == "BUY"
    assert signal["trigger"] == "EMA20_CROSS_ABOVE_EMA50"
    assert signal["score"] >= 75.0


def test_technical_scan_is_fundamental_free_and_reuses_paper_safety():
    market = FakeMarketData({"ABC": _frame("intraday")})
    paper = FakePaperAutoEntry()
    service = TechnicalTradingService(
        market_data=market,
        paper_auto_entry=paper,
        repository=FakeRepository(),
        indicator_engine=FakeIndicators(),
    )

    result = service.scan(
        symbols=["abc"],
        mode="intraday",
        execute_paper=True,
        run_id="tech-test",
        now=datetime(
            2026,
            10,
            19,
            10,
            0,
            tzinfo=ZoneInfo("Asia/Kolkata"),
        ),
    )

    assert result["status"] == "completed"
    assert result["mode"] == "intraday"
    assert result["interval"] == "15m"
    assert result["buy_candidates"] == 1
    assert result["top_picks"][0]["symbol"] == "ABC"
    assert result["top_picks"][0]["fundamentals_used"] is False
    assert result["paper"]["status"] == "executed"
    assert result["safety"]["paper_risk_governance_reused"] is True
    assert result["provider_observation"]["fallback_count"] == 0
    assert paper.calls[0]["scan_result"]["top_picks"][0][
        "execution_eligible"
    ] is True


def test_technical_backtest_uses_profile_interval_and_persists_result():
    frame = _frame("swing", rows=90)
    # Put a clean entry cross before the end and a later bearish reversal.
    frame.iloc[20, frame.columns.get_loc("EMA_20")] = 99.0
    frame.iloc[20, frame.columns.get_loc("EMA_50")] = 100.0
    frame.iloc[21, frame.columns.get_loc("EMA_20")] = 101.0
    frame.iloc[21, frame.columns.get_loc("EMA_50")] = 100.0
    frame.iloc[40, frame.columns.get_loc("EMA_20")] = 101.0
    frame.iloc[40, frame.columns.get_loc("EMA_50")] = 100.0
    frame.iloc[41:, frame.columns.get_loc("EMA_20")] = 94.0
    frame.iloc[41:, frame.columns.get_loc("EMA_50")] = 100.0
    frame.iloc[41:, frame.columns.get_loc("close")] = 93.0
    frame.iloc[41:, frame.columns.get_loc("MACD")] = 0.0
    frame.iloc[41:, frame.columns.get_loc("MACD_SIGNAL")] = 0.5
    frame.iloc[41:, frame.columns.get_loc("RSI")] = 45.0

    market = FakeMarketData({"ABC": frame})
    repository = FakeRepository()
    service = TechnicalTradingService(
        market_data=market,
        repository=repository,
        indicator_engine=FakeIndicators(),
    )

    result = service.backtest(
        symbol="ABC",
        mode="swing",
        period="1y",
        capital=100000.0,
        run_id="tech-bt-test",
        now=datetime(
            2026,
            10,
            19,
            20,
            0,
            tzinfo=ZoneInfo("Asia/Kolkata"),
        ),
    )

    assert result["status"] == "completed"
    assert result["strategy"]["name"] == "TECHNICAL_SWING"
    assert result["strategy"]["technical_only"] is True
    assert result["interval"] == "1d"
    assert result["safety"]["fundamentals_used"] is False
    assert market.calls[0] == ("ABC", "1y", "1d")
    assert repository.rows["tech-bt-test"]["strategy_name"] == "TECHNICAL_SWING"
    assert result["metrics"]["total_trades"] >= 1


def test_readiness_declares_kite_only_policy():
    service = TechnicalTradingService(
        market_data=FakeMarketData({"ABC": _frame("swing")}),
        paper_auto_entry=FakePaperAutoEntry(),
        repository=FakeRepository(),
        indicator_engine=FakeIndicators(),
    )

    readiness = service.readiness()

    assert readiness["data_policy"] == "kite_only"
    assert readiness["fundamentals_used"] is False
    assert readiness["enrichment_used"] is False
    assert readiness["broker_orders_allowed"] is False
    assert readiness["profiles"]["intraday"]["interval"] == "15m"
    assert readiness["profiles"]["swing"]["interval"] == "1d"
