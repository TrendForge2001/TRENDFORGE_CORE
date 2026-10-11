from __future__ import annotations

import pytest

from providers.nse_provider import NSEProvider


def fresh_nse_provider() -> NSEProvider:
    provider = object.__new__(NSEProvider)
    NSEProvider.__init__(provider)
    return provider


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        text="{}",
        content_type="application/json",
        payload=None,
    ):
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": content_type}
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_nse_rejects_non_json_response_with_diagnostic_context():
    provider = fresh_nse_provider()
    provider._session_ready = True

    response = FakeResponse(
        text="<html>challenge</html>",
        content_type="text/html",
    )

    with pytest.raises(RuntimeError, match="non-JSON response"):
        provider._decode_json_response(response)

    assert provider._session_ready is False


def test_nse_429_enters_provider_cooldown():
    provider = fresh_nse_provider()

    response = FakeResponse(
        status_code=429,
        text="Too Many Requests",
        content_type="text/plain",
    )

    with pytest.raises(RuntimeError, match="HTTP 429"):
        provider._decode_json_response(response)

    assert provider._cooldown_remaining() > 0
    assert provider.health()["status"] == "degraded"
    assert provider.health()["runtime_status"] == "rate_limited"


def test_nse_corporate_actions_use_scoped_current_endpoint_params():
    provider = fresh_nse_provider()
    captured = {}

    def fake_get(endpoint, params=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return []

    provider._get = fake_get
    result = provider.corporate_actions("LUPIN", days=90)

    assert result == []
    assert captured["endpoint"] == "/api/corporates-corporateActions"
    assert captured["params"]["index"] == "equities"
    assert captured["params"]["symbol"] == "LUPIN"
    assert "from_date" in captured["params"]
    assert "to_date" in captured["params"]


def test_nse_large_deals_use_combined_historical_endpoint():
    provider = fresh_nse_provider()
    calls = []

    def fake_get(endpoint, params=None):
        calls.append((endpoint, dict(params or {})))
        return {"data": []}

    provider._get = fake_get

    provider.bulk_deals(days=30)
    provider.block_deals(days=30)

    assert calls[0][0] == "/api/historicalOR/bulk-block-short-deals"
    assert calls[0][1]["optionType"] == "bulk_deals"
    assert calls[1][0] == "/api/historicalOR/bulk-block-short-deals"
    assert calls[1][1]["optionType"] == "block_deals"
    assert "from" in calls[0][1]
    assert "to" in calls[0][1]


def test_nse_shareholding_filings_use_symbol_scoped_endpoint():
    provider = fresh_nse_provider()
    captured = {}

    def fake_get(endpoint, params=None):
        captured["endpoint"] = endpoint
        captured["params"] = dict(params or {})
        return []

    provider._get = fake_get
    result = provider.shareholding_filings("LUPIN")

    assert result == []
    assert captured["endpoint"] == "/api/corporate-share-holdings-master"
    assert captured["params"] == {
        "index": "equities",
        "symbol": "LUPIN",
    }


def test_nse_public_document_rejects_non_nse_hosts():
    provider = fresh_nse_provider()

    with pytest.raises(ValueError, match="allowed archive hosts"):
        provider.public_document(
            "https://example.com/corporate/xbrl/SHP_TEST.xml"
        )


def test_nse_403_enters_access_cooldown():
    provider = fresh_nse_provider()

    response = FakeResponse(
        status_code=403,
        text="Forbidden",
        content_type="text/plain",
    )

    with pytest.raises(RuntimeError, match="HTTP 403"):
        provider._decode_json_response(response)

    health = provider.health()
    assert health["status"] == "degraded"
    assert health["runtime_status"] == "access_blocked"
    assert health["access_retry_after_seconds"] > 0


def test_nse_403_is_not_retried_repeatedly():
    provider = fresh_nse_provider()
    provider._session_ready = True

    class Session:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse(
                status_code=403,
                text="Forbidden",
                content_type="text/plain",
            )

    provider.session = Session()

    with pytest.raises(RuntimeError, match="HTTP 403"):
        provider._get("/api/test")

    assert provider.session.calls == 1
    assert provider._access_cooldown_remaining() > 0

    with pytest.raises(RuntimeError, match="access cooldown active"):
        provider._get("/api/test-2")

    assert provider.session.calls == 1


def _market_frame(base: float = 100.0):
    import pandas as pd

    return pd.DataFrame(
        {
            "Open": [base, base + 1],
            "High": [base + 2, base + 3],
            "Low": [base - 2, base - 1],
            "Close": [base + 1, base + 2],
            "Volume": [1000, 1100],
        }
    )


def test_market_adapter_prefers_bulk_provider_contract():
    from providers.market_data_adapter import MarketDataAdapter

    class Provider:
        def __init__(self):
            self.batch_calls = 0
            self.single_calls = 0

        def batch_candles_with_errors(
            self,
            symbols,
            period="1y",
            interval="1d",
        ):
            self.batch_calls += 1
            return {
                symbol: _market_frame()
                for symbol in symbols
            }, {}

        def candles(self, symbol, period="1y", interval="1d"):
            self.single_calls += 1
            return _market_frame()

    provider = Provider()
    adapter = MarketDataAdapter(provider, max_workers=8)
    results, failures = adapter.batch_candles_with_errors(
        ["AAA", "BBB", "CCC"],
        period="6mo",
        interval="1d",
    )

    assert failures == {}
    assert set(results) == {"AAA", "BBB", "CCC"}
    assert provider.batch_calls == 1
    assert provider.single_calls == 0
    assert list(results["AAA"].columns) == [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]


def test_routed_market_batch_falls_back_only_for_unresolved_symbols():
    from providers.routed_market_data_provider import (
        RoutedMarketDataProvider,
    )

    class Primary:
        def batch_candles_with_errors(
            self,
            symbols,
            period="1y",
            interval="1d",
        ):
            return {"AAA": _market_frame(100)}, {
                "BBB": "temporary upstream failure"
            }

    class Fallback:
        def __init__(self):
            self.calls = []

        def candles(self, symbol, period="1y", interval="1d"):
            self.calls.append(symbol)
            return _market_frame(200)

    fallback = Fallback()
    routed = RoutedMarketDataProvider(
        [Primary(), fallback],
        fallback_on_error=True,
    )
    results, failures = routed.batch_candles_with_errors(
        ["AAA", "BBB"],
        period="6mo",
        interval="1d",
    )

    assert failures == {}
    assert set(results) == {"AAA", "BBB"}
    assert fallback.calls == ["BBB"]
    assert routed.last_provider["AAA"] == "Primary"
    assert routed.last_provider["BBB"] == "Fallback"


def test_yahoo_batch_targeted_recovery_is_capped(monkeypatch):
    import pandas as pd
    from providers.yfinance_provider import YahooFinanceProvider

    provider = object.__new__(YahooFinanceProvider)
    provider.cache = {}
    provider._initialized = True

    payload = pd.concat(
        {"AAA.NS": _market_frame(100)},
        axis=1,
    )

    monkeypatch.setattr(
        provider,
        "download",
        lambda symbols, period="6mo", interval="1d": payload,
    )

    calls = []

    def fake_history(
        symbol,
        period="1y",
        interval="1d",
        auto_adjust=True,
    ):
        calls.append(symbol)
        return _market_frame(200)

    monkeypatch.setattr(provider, "historical_data", fake_history)

    results, failures = provider.batch_candles_with_errors(
        ["AAA", "BBB"],
        period="6mo",
        interval="1d",
    )

    assert failures == {}
    assert set(results) == {"AAA", "BBB"}
    assert calls == ["BBB"]


def test_yahoo_batch_does_not_fan_out_large_missing_set(monkeypatch):
    import pandas as pd
    from providers.yfinance_provider import YahooFinanceProvider

    provider = object.__new__(YahooFinanceProvider)
    provider.cache = {}
    provider._initialized = True

    payload = pd.concat(
        {"AAA.NS": _market_frame(100)},
        axis=1,
    )

    monkeypatch.setattr(
        provider,
        "download",
        lambda symbols, period="6mo", interval="1d": payload,
    )

    calls = []

    def fake_history(*args, **kwargs):
        calls.append(args[0])
        return _market_frame(200)

    monkeypatch.setattr(provider, "historical_data", fake_history)

    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    results, failures = provider.batch_candles_with_errors(symbols)

    assert set(results) == {"AAA"}
    assert set(failures) == {"BBB", "CCC", "DDD", "EEE", "FFF"}
    assert calls == []
