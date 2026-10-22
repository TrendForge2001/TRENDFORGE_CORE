"""Safe, bounded quote reads for the public trading watchlist."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from types import SimpleNamespace
import threading

import pytest

from services.trading_workspace_service import TradingWorkspaceService


class Universe:
    def __init__(self):
        self.symbol = "TCS"

    def load(self, name):
        return {
            "index": name,
            "source": "fixture",
            "members": [{"symbol": self.symbol, "name": "Test company"}],
        }


def workspace(provider, *, clock=None, universe=None):
    kwargs = {"clock": clock} if clock is not None else {}
    return TradingWorkspaceService(
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        universe_provider=universe or Universe(),
        provider_factory=SimpleNamespace(quote=lambda: provider),
        **kwargs,
    )


def test_watchlist_failure_redacts_response_and_logs_and_caches_failure(caplog):
    secret = "FIN_EDGE_KEY_SENTINEL/path?token=do-not-display"
    calls = []

    class Provider:
        def safe_quote(self, instruments):
            calls.append(instruments)
            raise RuntimeError(secret)

    service = workspace(Provider())
    with caplog.at_level(logging.WARNING, logger="trendforge.workspace"):
        first = service.watchlist("NIFTY 100")
        second = service.watchlist("NIFTY100")

    assert first["status"] == "degraded"
    assert first["quote_status"] == "unavailable"
    assert first["quote_error"] == "Kite quotes temporarily unavailable"
    assert first["quote_error_code"] == "WORKSPACE_QUOTES_UNAVAILABLE"
    reference = first["quote_error_reference"]
    assert len(reference) == 12
    assert second["quote_error_reference"] == reference
    assert first["quote_cache"]["cached"] is False
    assert second["quote_cache"]["cached"] is True
    assert len(calls) == 1
    assert len(caplog.records) == 1
    assert reference in caplog.text
    assert "RuntimeError" in caplog.text
    assert caplog.records[0].exc_info is None
    assert secret not in json.dumps(first)
    assert secret not in caplog.text
    assert all(first["rows"][0][key] is None for key in (
        "ltp", "day_change_rs", "day_change_pct",
    ))


def test_watchlist_success_cache_expires_and_exposes_quote_age():
    now = [10.0]
    calls = []

    class Provider:
        def safe_quote(self, instruments):
            calls.append(instruments)
            return {"NSE:TCS": {"last_price": 120.0, "ohlc": {"close": 100.0}}}

    service = workspace(Provider(), clock=lambda: now[0])
    first = service.watchlist("NIFTY 100")
    now[0] += 4.0
    second = service.watchlist("NIFTY 100")
    assert len(calls) == 1
    assert second["quote_cache"]["cached"] is True
    assert second["quote_cache"]["age_seconds"] == 4.0
    assert second["quote_cache"]["fetched_at"] == first["quote_cache"]["fetched_at"]
    assert second["rows"][0]["ltp"] == 120.0
    assert second["rows"][0]["day_change_pct"] == 20.0
    assert second["quote_error_reference"] is None
    now[0] += 1.0
    third = service.watchlist("NIFTY 100")
    assert len(calls) == 2
    assert third["quote_cache"]["cached"] is False
    assert third["quote_cache"]["age_seconds"] == 0.0
    assert third["quote_cache"]["ttl_seconds"] == 5.0


def test_concurrent_watchlists_share_one_quote_request():
    entered = threading.Event()
    release = threading.Event()
    calls = []

    class Provider:
        def safe_quote(self, instruments):
            calls.append(instruments)
            entered.set()
            assert release.wait(3.0)
            return {"NSE:TCS": {"last_price": 120.0}}

    service = workspace(Provider())
    with ThreadPoolExecutor(max_workers=8) as pool:
        requests = [pool.submit(service.watchlist, "NIFTY 100") for _ in range(8)]
        try:
            assert entered.wait(2.0)
        finally:
            release.set()
        results = [request.result(timeout=3.0) for request in requests]
    assert len(calls) == 1
    assert all(result["quote_status"] == "available" for result in results)
    assert sum(not result["quote_cache"]["cached"] for result in results) == 1


def test_watchlist_cache_tracks_members_and_is_bounded_to_supported_indexes():
    universe = Universe()
    calls = []

    class Provider:
        def safe_quote(self, instruments):
            calls.append(instruments)
            return {symbol: {"last_price": 100.0} for symbol in instruments}

    service = workspace(Provider(), universe=universe)
    service.watchlist("NIFTY 100")
    universe.symbol = "INFY"
    changed = service.watchlist("NIFTY 100")
    assert changed["rows"][0]["symbol"] == "INFY"
    assert changed["quote_cache"]["cached"] is False
    service.watchlist("NIFTY 200")
    service.watchlist("NIFTY 500")
    with pytest.raises(ValueError, match="index must be"):
        service.watchlist("arbitrary-public-input")
    assert len(calls) == 4
    assert len(service._quote_snapshots) == 3


def test_invalid_quote_shape_keeps_degraded_constituents():
    service = workspace(SimpleNamespace(safe_quote=lambda instruments: ["invalid"]))
    result = service.watchlist("NIFTY 100")
    assert result["status"] == "degraded"
    assert result["count"] == 1
    assert result["quote_error_code"] == "WORKSPACE_QUOTES_UNAVAILABLE"
    assert result["rows"][0]["ltp"] is None
