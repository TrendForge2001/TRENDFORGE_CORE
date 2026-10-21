from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient

from api.admin_auth import require_admin_api_key
from api.app import create_app
from database.database import Database
from database.migrations import trade_history
from database.repositories.trade_repository import TradeRepository
from services.strategy_paper_monitor_service import (
    StrategyPaperMonitorService,
)


def test_r7255_migration_adds_strategy_lineage_columns(tmp_path):
    db = Database(str(tmp_path / "legacy.db"))
    try:
        db.execute(
            """
            CREATE TABLE trade_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                side TEXT,
                quantity INTEGER,
                entry_price REAL,
                exit_price REAL,
                stoploss REAL,
                target REAL,
                pnl REAL,
                status TEXT,
                broker_order_id TEXT,
                created_at DATETIME
            )
            """
        )
        trade_history.migrate(db)
        columns = {
            row["name"]
            for row in db.fetchall(
                "PRAGMA table_info(trade_history)"
            )
        }
        for name in (
            "strategy_id",
            "strategy_name",
            "strategy_source",
            "source_scan_run_id",
            "validation_run_id",
            "strategy_score",
            "consensus_score",
            "entry_signal",
            "entry_bar_at",
            "exit_reason",
            "exit_signal",
            "exit_signal_at",
            "exit_strategy_score",
        ):
            assert name in columns
    finally:
        db.close()


def test_r7255_repository_attributes_strategy_performance(tmp_path):
    db = Database(str(tmp_path / "trades.db"))
    try:
        trade_history.migrate(db)
        repo = TradeRepository(db=db)
        first = repo.save(
            symbol="TCS",
            side="BUY",
            quantity=10,
            entry_price=100.0,
            stoploss=95.0,
            target=110.0,
            strategy_id="tpl_supertrend_rsi",
            strategy_name="Template · Supertrend + RSI",
            strategy_source="template",
            source_scan_run_id="scan-1",
            validation_run_id="validation-1",
            strategy_score=100,
            consensus_score=82.5,
            entry_signal="BUY",
            entry_bar_at="2026-10-21T10:00:00+05:30",
            trade_mode="swing",
        )
        second = repo.save(
            symbol="INFY",
            side="BUY",
            quantity=10,
            entry_price=100.0,
            strategy_id="tpl_supertrend_rsi",
            strategy_name="Template · Supertrend + RSI",
            strategy_source="template",
            trade_mode="swing",
        )
        repo.close_trade(
            first,
            110.0,
            exit_reason="STRATEGY_EXIT",
            exit_signal="EXIT",
            exit_signal_at="2026-10-22T15:30:00+05:30",
            exit_strategy_score=75.0,
        )
        repo.close_trade(
            second,
            95.0,
            exit_reason="STOPLOSS",
        )

        row = dict(repo.get(first))
        assert row["strategy_id"] == "tpl_supertrend_rsi"
        assert row["source_scan_run_id"] == "scan-1"
        assert row["validation_run_id"] == "validation-1"
        assert row["exit_reason"] == "STRATEGY_EXIT"
        assert row["exit_signal"] == "EXIT"
        assert row["exit_strategy_score"] == 75.0

        performance = repo.strategy_performance()
        assert len(performance) == 1
        perf = performance[0]
        assert perf["closed_trades"] == 2
        assert perf["wins"] == 1
        assert perf["losses"] == 1
        assert perf["win_rate_pct"] == 50.0
        assert perf["net_pnl"] == 50.0

        trades = repo.strategy_trades("tpl_supertrend_rsi")
        assert len(trades) == 2
    finally:
        db.close()


class FakeMarketData:
    def batch_candles_with_errors(self, symbols, *, period, interval):
        index = pd.date_range(
            "2026-01-01",
            periods=130,
            freq="D",
        )
        frame = pd.DataFrame(
            {
                "open": [100.0] * 130,
                "high": [102.0] * 130,
                "low": [98.0] * 130,
                "close": [100.0] * 130,
                "volume": [1000.0] * 130,
            },
            index=index,
        )
        return {symbol: frame.copy() for symbol in symbols}, {}


class FakeIndicators:
    def calculate(self, frame):
        return frame


class FakeStrategies:
    def __init__(self, signal="EXIT"):
        self.signal = signal

    def evaluate(
        self,
        frame,
        *,
        mode,
        interval,
        source,
        strategy_ids,
    ):
        strategy_id = strategy_ids[0]
        return {
            "evaluations": [
                {
                    "strategy_id": strategy_id,
                    "status": "evaluated",
                    "signal": self.signal,
                    "score": 75.0,
                    "passed_checks": ["exit_rule"],
                    "failed_checks": [],
                }
            ]
        }


class FakeScanner:
    def __init__(self, signal="EXIT"):
        self.market_data = FakeMarketData()
        self.indicators = FakeIndicators()
        self.strategies = FakeStrategies(signal=signal)

    @staticmethod
    def _mode_config(mode, period):
        if mode == "intraday":
            return mode, "15m", "60d"
        return mode, "1d", "2y"

    @staticmethod
    def _completed_bars(frame, *, interval, now=None):
        return frame

    @staticmethod
    def _intraday_session_overrides(frame):
        return frame

    @staticmethod
    def _label(value):
        return pd.Timestamp(value).isoformat()


class FakeQuote:
    def validate_live_session(self):
        return True

    def safe_ltp(self, instruments):
        return {
            key: {"last_price": 95.0}
            for key in instruments
        }


class FakeRepo:
    def strategy_performance(self):
        return [
            {
                "strategy_id": "tpl_supertrend_rsi",
                "closed_trades": 2,
                "net_pnl": 50.0,
            }
        ]

    def strategy_trades(self, strategy_id=None, *, limit=200):
        return [
            {
                "strategy_id": strategy_id or "tpl_supertrend_rsi",
                "status": "CLOSED",
            }
        ]


class FakePaper:
    def __init__(self):
        self.position = SimpleNamespace(
            symbol="TCS",
            quantity=10,
            average_price=100.0,
            ltp=100.0,
            side="BUY",
            stoploss=90.0,
            target2=120.0,
            trade_mode="swing",
            strategy_id="tpl_supertrend_rsi",
            strategy_name="Template · Supertrend + RSI",
            strategy_source="template",
            source_scan_run_id="scan-1",
            validation_run_id="validation-1",
            strategy_score=100.0,
            consensus_score=82.5,
            entry_signal="BUY",
            entry_bar_at="2026-10-21T10:00:00+05:30",
            pnl=0.0,
            pnl_percent=0.0,
        )
        self.runtime = SimpleNamespace(
            portfolio=SimpleNamespace(
                positions={"TCS": self.position}
            ),
            trades=FakeRepo(),
        )
        self.close_calls = []

    def close_strategy_exit(self, symbol, exit_price, **kwargs):
        self.close_calls.append(
            {
                "symbol": symbol,
                "exit_price": exit_price,
                **kwargs,
            }
        )
        self.runtime.portfolio.positions.pop(symbol, None)
        return {
            "status": "closed",
            "closed": {
                "symbol": symbol,
                "exit_price": exit_price,
                "reason": "STRATEGY_EXIT",
                "strategy_id": "tpl_supertrend_rsi",
                "pnl": -50.0,
            },
        }


def test_r7255_exit_signal_closes_only_through_paper_service():
    paper = FakePaper()
    monitor = StrategyPaperMonitorService(
        scanner_service=FakeScanner(signal="EXIT"),
        paper_service=paper,
        quote_provider=FakeQuote(),
        enabled=False,
    )

    result = monitor.tick(
        now=datetime(2026, 10, 21, 14, 0),
        force=True,
    )

    assert result["status"] == "closed"
    assert len(result["exit_signals"]) == 1
    assert len(result["closed"]) == 1
    assert len(paper.close_calls) == 1
    call = paper.close_calls[0]
    assert call["symbol"] == "TCS"
    assert call["exit_price"] == 95.0
    assert call["exit_signal"] == "EXIT"
    assert call["exit_strategy_score"] == 75.0
    assert result["broker_orders_allowed"] is False


def test_r7255_hold_signal_never_closes():
    paper = FakePaper()
    monitor = StrategyPaperMonitorService(
        scanner_service=FakeScanner(signal="HOLD"),
        paper_service=paper,
        quote_provider=FakeQuote(),
        enabled=True,
    )

    result = monitor.tick(
        now=datetime(2026, 10, 21, 14, 0),
    )

    assert result["status"] == "monitored"
    assert result["exit_signals"] == []
    assert result["closed"] == []
    assert paper.close_calls == []
    assert "TCS" in paper.runtime.portfolio.positions


def test_r7255_performance_reports_open_and_closed_strategy_books():
    paper = FakePaper()
    monitor = StrategyPaperMonitorService(
        scanner_service=FakeScanner(),
        paper_service=paper,
        quote_provider=FakeQuote(),
        enabled=False,
    )

    performance = monitor.performance()
    trades = monitor.trades("tpl_supertrend_rsi")

    assert performance["strategy_count"] == 1
    assert performance["rows"][0]["net_pnl"] == 50.0
    assert performance["open_strategy_positions"][0]["symbol"] == "TCS"
    assert trades["count"] == 1
    assert trades["broker_orders_allowed"] is False


class ApiStrategyMonitor:
    def health(self):
        return {
            "status": "disabled",
            "version": "R72.5.5-v1",
            "broker_orders_allowed": False,
        }

    def tick(self, *, force=False):
        assert force is True
        return {
            "status": "monitored",
            "version": "R72.5.5-v1",
            "closed": [],
            "broker_orders_allowed": False,
        }

    def performance(self):
        return {
            "status": "ready",
            "version": "R72.5.5-v1",
            "rows": [],
            "open_strategy_positions": [],
            "broker_orders_allowed": False,
        }

    def trades(self, strategy_id=None, *, limit=200):
        return {
            "status": "ready",
            "strategy_id": strategy_id,
            "count": 0,
            "rows": [],
            "limit": limit,
            "broker_orders_allowed": False,
        }


class ApiFactory:
    def __init__(self):
        self.monitor = ApiStrategyMonitor()

    def strategy_paper_monitor_service(self):
        return self.monitor


def test_r7255_api_surfaces_monitor_and_attribution():
    factory = ApiFactory()
    app = create_app(factory)
    app.dependency_overrides[require_admin_api_key] = lambda: True

    with TestClient(app) as client:
        readiness = client.get("/paper/strategy-monitor/readiness")
        tick = client.post("/paper/strategy-monitor/tick", json={})
        performance = client.get("/paper/strategy-performance")
        trades = client.get(
            "/paper/strategy-trades",
            params={
                "strategy_id": "tpl_supertrend_rsi",
                "limit": 50,
            },
        )

    assert readiness.status_code == 200
    assert readiness.json()["version"] == "R72.5.5-v1"
    assert tick.status_code == 200
    assert tick.json()["broker_orders_allowed"] is False
    assert performance.status_code == 200
    assert trades.status_code == 200
    assert trades.json()["strategy_id"] == "tpl_supertrend_rsi"
