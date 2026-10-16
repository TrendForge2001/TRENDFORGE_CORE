from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.portfolio_performance_service import (
    PortfolioPerformanceService,
)


IST = ZoneInfo("Asia/Kolkata")


class FakePortfolioRepository:
    def __init__(self):
        self.rows = [
            {
                "symbol": "TCS",
                "book": "HOLDING",
                "sector": "IT",
                "quantity": 2,
                "average_price": 3000.0,
                "ltp": 3200.0,
                "investment": 6000.0,
                "current_value": 6400.0,
                "pnl": 400.0,
                "updated_at": "2026-10-16T10:00:00+05:30",
            },
            {
                "symbol": "RELIANCE",
                "book": "POSITION",
                "sector": "Energy",
                "quantity": 1,
                "average_price": 2500.0,
                "ltp": 2450.0,
                "investment": 2500.0,
                "current_value": 2450.0,
                "pnl": -50.0,
                "updated_at": "2026-10-16T10:01:00+05:30",
            },
        ]

    def all(self):
        return list(self.rows)

    def investment(self):
        return 8500.0

    def portfolio_value(self):
        return 8850.0

    def total_pnl(self):
        return 350.0

    def close(self):
        pass


class FakeTradeRepository:
    def __init__(self):
        self.rows = [
            {
                "id": 1,
                "symbol": "TCS",
                "side": "BUY",
                "quantity": 2,
                "entry_price": 3000.0,
                "exit_price": 3100.0,
                "pnl": 200.0,
                "status": "CLOSED",
                "created_at": "2026-10-15T10:00:00+05:30",
                "closed_at": "2026-10-15T14:00:00+05:30",
            },
            {
                "id": 2,
                "symbol": "INFY",
                "side": "BUY",
                "quantity": 1,
                "entry_price": 1500.0,
                "exit_price": 1400.0,
                "pnl": -100.0,
                "status": "CLOSED",
                "created_at": "2026-10-16T10:00:00+05:30",
                "closed_at": "2026-10-16T14:00:00+05:30",
            },
            {
                "id": 3,
                "symbol": "SBIN",
                "side": "BUY",
                "quantity": 10,
                "entry_price": 800.0,
                "exit_price": 820.0,
                "pnl": 200.0,
                "status": "CLOSED",
                "created_at": "2026-10-01T10:00:00+05:30",
                "closed_at": None,
            },
            {
                "id": 4,
                "symbol": "OLD",
                "side": "BUY",
                "quantity": 1,
                "entry_price": 100.0,
                "exit_price": 90.0,
                "pnl": -10.0,
                "status": "CLOSED",
                "created_at": "2025-01-01T10:00:00+05:30",
                "closed_at": None,
            },
        ]

    def closed_trades(self):
        return list(self.rows)

    def close(self):
        pass


def service():
    return PortfolioPerformanceService(
        portfolio_repository=FakePortfolioRepository(),
        trade_repository=FakeTradeRepository(),
    )


def test_portfolio_snapshot_separates_books_and_summarizes_value():
    result = service().portfolio()

    assert result["status"] == "ready"
    assert result["count"] == 2
    assert result["holding_count"] == 1
    assert result["position_count"] == 1
    assert result["investment"] == 8500.0
    assert result["portfolio_value"] == 8850.0
    assert result["total_pnl"] == 350.0
    assert result["total_pnl_pct"] == 4.12
    assert result["book_summary"][0]["book"] == "HOLDING"
    assert result["sector_summary"][0]["sector"] == "IT"


def test_monthly_pnl_uses_close_timestamp_and_legacy_fallback():
    result = service().pnl_statement(
        period="monthly",
        now=datetime(2026, 10, 16, 20, 0, tzinfo=IST),
    )

    assert result["summary"]["trade_count"] == 3
    assert result["summary"]["net_pnl"] == 300.0
    assert result["summary"]["winning_trades"] == 2
    assert result["summary"]["losing_trades"] == 1
    assert {
        trade["date_basis"]
        for trade in result["trades"]
    } == {"closed_at", "legacy_entry_fallback"}
    assert all(
        trade["symbol"] != "OLD"
        for trade in result["trades"]
    )


def test_daily_pnl_filters_to_current_calendar_day():
    result = service().pnl_statement(
        period="daily",
        now=datetime(2026, 10, 16, 20, 0, tzinfo=IST),
    )

    assert result["summary"]["trade_count"] == 1
    assert result["summary"]["net_pnl"] == -100.0
    assert result["trades"][0]["symbol"] == "INFY"


def test_performance_reports_win_rate_profit_factor_and_drawdown():
    result = service().performance(
        period="monthly",
        now=datetime(2026, 10, 16, 20, 0, tzinfo=IST),
    )

    summary = result["summary"]
    assert summary["trade_count"] == 3
    assert summary["win_rate_pct"] == 66.67
    assert summary["profit_factor"] == 4.0
    assert summary["expectancy"] == 100.0
    assert summary["maximum_drawdown"] == 100.0
    assert summary["best_trade"]["pnl"] == 200.0
    assert summary["worst_trade"]["pnl"] == -100.0
    assert result["equity_curve"][-1]["cumulative_pnl"] == 300.0


def test_invalid_period_is_rejected():
    try:
        service().pnl_statement(period="quarterly")
    except ValueError as exc:
        assert "daily, weekly, monthly, yearly or all" in str(exc)
    else:
        raise AssertionError("invalid period must fail")
