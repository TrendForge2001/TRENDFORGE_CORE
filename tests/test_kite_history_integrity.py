"""The real normalization/filtering pipeline preserves genuine session bars."""

import json
import math
import secrets
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import requests

from indicators.ema_pivot import add_ema_pivot_indicators
from providers.kite_provider import KiteProvider
from providers.kite_rest_client import KiteRESTClient
from providers.market_data_adapter import MarketDataAdapter
from services.technical_trading_service import TechnicalTradingService

ZONE = ZoneInfo("Asia/Kolkata")


@pytest.mark.parametrize("normal_bars", [24, 25])
def test_raw_session_bars_survive_normalization_and_completed_filter(
    monkeypatch, normal_bars
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Candle integrity tests cannot call a real broker")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    stamps = [
        *pd.date_range("2026-11-04 09:15", periods=normal_bars, freq="15min", tz=ZONE),
        *pd.date_range("2026-11-05 09:15", periods=normal_bars, freq="15min", tz=ZONE),
        *pd.date_range("2026-11-06 09:15", periods=3, freq="15min", tz=ZONE),
    ]
    rows = [
        [stamp.isoformat(), 100 + i, 103 + i, 99 + i, 102 + i, 1000 + i]
        for i, stamp in enumerate(stamps)
    ]

    class Transport:
        calls = []

        def request(self, method, url, **kwargs):
            assert method == "GET"
            assert url == "https://api.kite.trade/instruments/historical/123/15minute"
            self.calls.append(kwargs)
            body = {"status": "success", "data": {"candles": rows}}
            return SimpleNamespace(
                status_code=200,
                headers={"Content-Type": "application/json"},
                content=json.dumps(body).encode(),
                json=lambda: body,
            )

    transport = Transport()
    broker = object.__new__(KiteProvider)
    broker.access_token = secrets.token_hex(16)
    broker.kite = KiteRESTClient(
        api_key=secrets.token_hex(12),
        access_token=broker.access_token,
        session=transport,
    )
    now = datetime(2026, 11, 6, 9, 45, tzinfo=ZONE)
    broker.instrument_token_for_symbol = lambda _: 123
    broker._pace_history = lambda: None
    broker._history_window = lambda _: (
        stamps[0].to_pydatetime().astimezone(UTC),
        now.astimezone(UTC),
    )
    provided = broker.candles("RELIANCE", period="30d", interval="15m")
    normalized = MarketDataAdapter._normalize("RELIANCE", provided)
    completed = TechnicalTradingService._completed_bars(
        normalized, interval="15m", now=now
    )
    assert list(provided.index) == list(normalized.index) == stamps
    assert list(completed.index) == stamps[:-1]
    assert transport.calls[0]["params"]["to"] == "2026-11-06 09:45:00"
    previous = completed.loc[completed.index.date == datetime(2026, 11, 5).date()]
    assert len(previous) == normal_bars
    assert any(stamp.hour == 15 and stamp.minute == 15 for stamp in previous.index) == (
        normal_bars == 25
    )
    # A real completed 15:15 bar retains its OHLCV, not just its timestamp.
    if normal_bars == 25:
        original = rows[2 * normal_bars - 1]
        assert list(previous.iloc[-1]) == original[1:]
    indicators = add_ema_pivot_indicators(completed.copy())
    for key in (
        "TRAD_DAY_P",
        "TRAD_DAY_R1",
        "TRAD_DAY_R2",
        "TRAD_DAY_S1",
        "TRAD_DAY_S2",
    ):
        assert math.isfinite(indicators.iloc[-1][key]) == (normal_bars == 25)
