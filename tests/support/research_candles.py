"""Deterministic, broker-free daily and 60-day intraday research data."""

import numpy as np
import pandas as pd


class SyntheticMarket:
    def batch_candles_with_errors(self, symbols, *, interval, **kwargs):
        if interval == "15m":
            days = pd.bdate_range("2026-09-07", "2026-11-06")
            index = pd.DatetimeIndex(
                [
                    day + pd.Timedelta(hours=9, minutes=15 + bar * 15)
                    for day in days
                    for bar in range(25)
                ]
            ).tz_localize("Asia/Kolkata")
        else:
            index = pd.bdate_range("2024-01-01", periods=500, tz="Asia/Kolkata")
        x = np.arange(len(index))
        close = 100 + x * 0.004 + np.sin(x / 9) * 5 + np.sin(x / 2) * 0.5
        raw = pd.DataFrame(
            {
                "open": close - 0.15,
                "high": close + 0.8,
                "low": close - 0.9,
                "close": close,
                "volume": 2000.0 + (x % 17) * 100,
            },
            index=index,
        )
        return {symbol: raw.copy() for symbol in symbols}, {}


def technical_service(database):
    from database.repositories.backtest_results import BacktestResultsRepository
    from services.technical_trading_service import TechnicalTradingService

    return TechnicalTradingService(
        market_data=SyntheticMarket(),
        repository=BacktestResultsRepository(db_path=database),
    )
