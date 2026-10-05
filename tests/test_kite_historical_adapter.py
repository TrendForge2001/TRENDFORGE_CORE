from __future__ import annotations

import pandas as pd

from providers.kite_historical_adapter import KiteHistoricalAdapter


class FakeProvider:
    def safe_historical(self, token, start, end, interval):
        assert token == 12345
        return [{
            "date": "2026-08-18",
            "open": 100,
            "high": 103,
            "low": 99,
            "close": 102,
            "volume": 1000,
        }]


class FakeInstruments:
    def token(self, symbol):
        return 12345 if symbol == "ABC" else None


def test_kite_adapter_resolves_token_and_normalizes_ohlcv():
    adapter = KiteHistoricalAdapter(FakeProvider(), FakeInstruments())
    frame = adapter.candles("ABC", period="1mo", interval="day")

    assert isinstance(frame, pd.DataFrame)
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert float(frame.iloc[-1]["close"]) == 102.0


def test_kite_adapter_rejects_unknown_symbol():
    adapter = KiteHistoricalAdapter(FakeProvider(), FakeInstruments())
    try:
        adapter.candles("UNKNOWN")
    except KeyError as exc:
        assert "UNKNOWN" in str(exc)
    else:
        raise AssertionError("Expected missing instrument token")
