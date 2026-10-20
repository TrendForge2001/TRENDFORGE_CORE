from __future__ import annotations

from services.technical_validation_service import TechnicalValidationService


class FakeTechnical:
    market_data = object()
    indicators = object()


def test_r715_aggregate_keeps_universes_separate():
    service = TechnicalValidationService(
        technical_service=FakeTechnical(),
        universe_provider=object(),
    )
    scanner = [
        {
            "symbol": "AAA",
            "mode": "swing",
            "signal": "BUY",
            "in_nifty100": True,
            "in_nifty200": True,
            "in_nifty500": True,
        },
        {
            "symbol": "BBB",
            "mode": "swing",
            "signal": "HOLD",
            "in_nifty100": False,
            "in_nifty200": True,
            "in_nifty500": True,
        },
    ]
    backtests = [
        {
            "symbol": "AAA",
            "mode": "swing",
            "status": "completed",
            "final_capital": 110000.0,
            "net_profit": 10000.0,
            "return_pct": 10.0,
            "max_drawdown_pct": 3.0,
            "transaction_costs": 100.0,
            "slippage_impact_estimate": 50.0,
            "in_nifty100": True,
            "in_nifty200": True,
            "in_nifty500": True,
        },
        {
            "symbol": "BBB",
            "mode": "swing",
            "status": "completed",
            "final_capital": 95000.0,
            "net_profit": -5000.0,
            "return_pct": -5.0,
            "max_drawdown_pct": 8.0,
            "transaction_costs": 80.0,
            "slippage_impact_estimate": 40.0,
            "in_nifty100": False,
            "in_nifty200": True,
            "in_nifty500": True,
        },
    ]
    trades = [
        {
            "mode": "swing",
            "net_pnl": 10000.0,
            "in_nifty100": True,
            "in_nifty200": True,
            "in_nifty500": True,
        },
        {
            "mode": "swing",
            "net_pnl": -5000.0,
            "in_nifty100": False,
            "in_nifty200": True,
            "in_nifty500": True,
        },
    ]
    rows = service._aggregate(
        scanner_rows=scanner,
        backtests=backtests,
        trades=trades,
        capital=100000.0,
    )
    n100 = next(
        row for row in rows
        if row["universe"] == "NIFTY 100" and row["mode"] == "swing"
    )
    n200 = next(
        row for row in rows
        if row["universe"] == "NIFTY 200" and row["mode"] == "swing"
    )
    assert n100["completed_symbols"] == 1
    assert n100["net_pnl"] == 10000.0
    assert n200["completed_symbols"] == 2
    assert n200["net_pnl"] == 5000.0
    assert n200["return_on_aggregate_test_capital_pct"] == 2.5


def test_r715_monthly_pnl_expands_nested_universe_membership():
    service = TechnicalValidationService(
        technical_service=FakeTechnical(),
        universe_provider=object(),
    )
    rows = service._monthly_pnl(
        [
            {
                "mode": "intraday",
                "exit_at": "2026-10-20T10:00:00+05:30",
                "gross_pnl": 1200.0,
                "transaction_costs": 200.0,
                "net_pnl": 1000.0,
                "in_nifty100": True,
                "in_nifty200": True,
                "in_nifty500": True,
            }
        ]
    )
    assert len(rows) == 3
    assert all(row["month"] == "2026-10" for row in rows)
    assert all(row["net_pnl"] == 1000.0 for row in rows)
