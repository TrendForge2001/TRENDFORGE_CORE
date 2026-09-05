from backtest.equity_curve import EquityCurve
from backtest.max_drawdown import MaxDrawdown
from backtest.performance_metrics import PerformanceMetrics
from backtest.sharpe_ratio import SharpeRatio


def test_performance_metrics_empty_trades():
    metrics = PerformanceMetrics([])
    assert metrics.total_trades == 0
    assert metrics.win_rate == 0
    assert metrics.net_profit == 0
    assert metrics.expectancy == 0


def test_equity_curve_accumulates_pnl():
    first = type("Trade", (), {"pnl": 100})()
    second = type("Trade", (), {"pnl": -40})()
    assert EquityCurve().build([first, second]) == [100, 60]


def test_max_drawdown_handles_empty_and_peak_to_trough():
    assert MaxDrawdown().calculate([]) == 0.0
    assert MaxDrawdown().calculate([100, 120, 90, 110]) == 25.0


def test_sharpe_ratio_handles_zero_variance():
    assert SharpeRatio().calculate([]) == 0.0
    assert SharpeRatio().calculate([0.01, 0.01]) == 0.0
