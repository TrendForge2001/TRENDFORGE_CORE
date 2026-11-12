"""Artificial weekly recovery examples, never historical SBIN observations."""

import numpy as np
import pandas as pd

NOW = pd.Timestamp("2026-11-09T08:00:00+05:30")


def example_history():
    index = pd.bdate_range("2021-11-01", "2026-11-06", tz="Asia/Kolkata")
    close = 100 + np.arange(len(index)) * 0.015
    frame = pd.DataFrame(
        {
            "open": close - 0.02,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )
    # Explicitly broad prior-year range gives these manufactured examples a
    # reachable overhead R2. It is fixture construction, not a market forecast.
    frame.loc["2025-01-02", "high"] = 160.0
    frame.loc["2025-01-03", "low"] = 60.0
    for friday in ("2026-03-27", "2026-06-26", "2026-10-30"):
        stamp = pd.Timestamp(friday, tz="Asia/Kolkata")
        previous_monday, previous_friday = (
            stamp - pd.Timedelta(days=11),
            stamp - pd.Timedelta(days=7),
        )
        monday = stamp - pd.Timedelta(days=4)
        base = float(frame.loc[stamp, "close"])
        frame.loc[previous_monday, "open"] = base + 2
        frame.loc[previous_monday, "high"] = base + 2.3
        frame.loc[previous_friday, "close"] = base - 2
        frame.loc[previous_friday, "low"] = base - 2.3
        frame.loc[monday, "open"] = base - 3
        frame.loc[monday, "low"] = base - 3.3
        frame.loc[stamp, "close"] = base + 4
        frame.loc[stamp, "high"] = base + 4.3
        frame.loc[stamp, "volume"] = 11000
    frame.loc["2026-03-31", "high"] = 240.0
    frame.loc["2026-06-30", "low"] = 70.0
    return frame


class ExampleMarket:
    def __init__(self, frame=None):
        self.frame = example_history() if frame is None else frame
        self.calls = []

    def batch_candles_with_errors(self, symbols, *, interval, period):
        self.calls.append({"interval": interval, "period": period})
        assert interval == "1d" and period == "5y"
        return {symbol: self.frame.copy() for symbol in symbols}, {}

    def place_order(self, **kwargs):
        raise AssertionError("Research fixtures must never submit a broker order")
