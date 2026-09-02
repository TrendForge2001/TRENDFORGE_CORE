from datetime import datetime
from types import SimpleNamespace

from execution.paper_trading import PaperTrading
from execution.portfolio_manager import PortfolioManager
from execution.risk_monitor import RiskMonitor
from execution.target_manager import TargetManager


def make_order(side="BUY"):
    return SimpleNamespace(
        symbol="TEST",
        side=side,
        quantity=10,
        price=100.0,
        stoploss=95.0,
        target1=105.0,
        target2=110.0,
        target3=120.0,
        strategy="test",
        timestamp=datetime(2026, 1, 1),
    )


def test_paper_trading_is_side_aware():
    candle = SimpleNamespace(close=110.0, timestamp=datetime(2026, 1, 2))

    long_trade = PaperTrading().execute(make_order("BUY"), candle)
    short_trade = PaperTrading().execute(make_order("SHORT"), candle)

    assert long_trade.pnl == 100.0
    assert short_trade.pnl == -100.0


def test_portfolio_manager_tracks_side_aware_pnl():
    trade = PaperTrading().execute(
        make_order("SHORT"),
        SimpleNamespace(close=95.0, timestamp=datetime(2026, 1, 2)),
    )
    portfolio = PortfolioManager()
    portfolio.add(trade)
    portfolio.update("TEST", 90.0)

    assert portfolio.positions["TEST"].side == "SHORT"
    assert portfolio.total_pnl() == 100.0


def test_risk_monitor_rejects_invalid_capital():
    monitor = RiskMonitor()
    portfolio = SimpleNamespace(positions={})

    assert monitor.validate(portfolio, 0, 0) is False
    assert monitor.validate(portfolio, -1, 100000) is False
    assert monitor.validate(portfolio, 50000, 100000) is True


def test_target_manager_progresses_through_targets():
    position = SimpleNamespace(
        ltp=100.0,
        target1=105.0,
        target2=110.0,
        target3=120.0,
    )
    manager = TargetManager()

    assert manager.next_target(position) == 105.0
    position.ltp = 106.0
    assert manager.next_target(position) == 110.0
    position.ltp = 111.0
    assert manager.next_target(position) == 120.0
    position.ltp = 125.0
    assert manager.next_target(position) == 120.0
