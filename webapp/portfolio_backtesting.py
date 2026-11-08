"""Backtesting setup; completed batch reports are shown on Reports."""

from webapp.backtest_trade_report import validate_result as validate_result
from webapp.research_workspace import render_research_workspace

RESULT_KEY = "tf_r726_backtest_result"


def render_portfolio_backtesting(client, *, authorized):
    render_research_workspace(
        client, authorized=authorized, key="backtest", backtest=True
    )
