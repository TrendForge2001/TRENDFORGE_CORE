from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner


class FakeUniverse:
    def load(self, index_name, *, force_refresh=False):
        assert index_name in {"NIFTY 100", "NIFTY 200", "NIFTY 500"}
        count = {"NIFTY 100": 100, "NIFTY 200": 200, "NIFTY 500": 500}[index_name]
        return {
            "index": index_name,
            "source": "TEST",
            "security_count": count,
            "minimum_security_count": count,
            "fetched_at": "2026-10-20T00:00:00+00:00",
            "members": [{"symbol": f"S{i:03d}"} for i in range(count)],
        }

    def health(self):
        return {"status": "runtime_verified", "provider": "FakeUniverse"}


class FakeMarketData:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def begin_observation(self):
        pass

    def batch_candles_with_errors(self, symbols, *, period, interval):
        self.calls.append(
            {
                "symbols": list(symbols),
                "period": period,
                "interval": interval,
            }
        )
        return {symbol: self.frame.copy() for symbol in symbols}, {}

    def observability_snapshot(self, symbols=None):
        return {"provider": "fake", "symbols": list(symbols or [])}

    def health(self):
        return {"status": "healthy", "provider": "fake"}


def _daily_frame(rows=320):
    index = pd.date_range("2025-01-01", periods=rows, freq="B")
    x = np.arange(rows, dtype=float)
    close = 100 + x * 0.06 + np.sin(x / 8.0)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000 + (x % 11) * 25_000,
        },
        index=index,
    )


def test_scanner_runs_nifty100_source_swing_without_execution():
    market = FakeMarketData(_daily_frame())
    service = MultiStrategyNiftyScanner(
        market_data=market,
        universe_provider=FakeUniverse(),
    )

    result = service.scan(
        universe="NIFTY 100",
        mode="swing",
        source="user_notebook",
        top_n=10,
        limit=2,
        now=pd.Timestamp("2026-10-20 18:00", tz="Asia/Kolkata").to_pydatetime(),
    )

    assert result["status"] == "completed"
    assert result["requested_symbols"] == 2
    assert result["completed_symbols"] == 2
    assert result["universe"] == "NIFTY 100"
    assert market.calls[0]["interval"] == "1d"
    assert market.calls[0]["period"] == "2y"
    assert result["safety"]["scanner_only"] is True
    assert result["safety"]["paper_execution_allowed"] is False
    assert result["safety"]["paper_orders_created"] is False
    assert result["safety"]["broker_orders_allowed"] is False
    assert result["safety"]["fundamentals_used"] is False


def test_trigger_validates_before_starting_background_worker():
    service = MultiStrategyNiftyScanner(
        market_data=FakeMarketData(_daily_frame()),
        universe_provider=FakeUniverse(),
    )

    with pytest.raises(ValueError, match="source"):
        service.trigger(
            universe="NIFTY 100",
            mode="swing",
            source="bad-source",
        )


def test_status_contract_never_exposes_thread_object():
    service = MultiStrategyNiftyScanner(
        market_data=FakeMarketData(_daily_frame()),
        universe_provider=FakeUniverse(),
    )
    payload = service.status()

    assert "thread" not in payload
    assert payload["safety"]["broker_orders_allowed"] is False
