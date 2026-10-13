from __future__ import annotations

import pandas as pd
import pytest

from providers.provider_circuit_breaker import ProviderCircuitBreaker
from providers.routed_market_data_provider import RoutedMarketDataProvider
from providers.yfinance_provider import YahooFinanceProvider
from providers.nse_provider import NSEProvider


def _frame(base: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [base, base + 1],
            "High": [base + 2, base + 3],
            "Low": [base - 2, base - 1],
            "Close": [base + 1, base + 2],
            "Volume": [1000, 1100],
        }
    )


def test_provider_circuit_breaker_opens_after_failure_budget(monkeypatch):
    import providers.provider_circuit_breaker as breaker_module

    clock = [1000.0]
    monkeypatch.setattr(
        breaker_module.time,
        "time",
        lambda: clock[0],
    )

    breaker = ProviderCircuitBreaker(
        "YahooFinanceProvider",
        failure_threshold=2,
        cooldown_seconds=120,
    )

    assert breaker.allow_request() is True
    assert breaker.record_failure("HTTP 503") is False
    assert breaker.health()["state"] == "closed"

    assert breaker.record_failure("HTTP 503") is True
    health = breaker.health()
    assert health["state"] == "open"
    assert health["consecutive_failures"] == 2
    assert health["retry_after_seconds"] == 120
    assert breaker.allow_request() is False

    clock[0] += 121
    assert breaker.allow_request() is True
    health = breaker.health()
    assert health["state"] == "closed"
    assert health["consecutive_failures"] == 0


def test_routed_provider_skips_open_primary_circuit_on_next_batch():
    class Primary:
        def __init__(self):
            self.calls = 0

        def batch_candles_with_errors(
            self,
            symbols,
            period="1y",
            interval="1d",
        ):
            self.calls += 1
            return {}, {
                symbol: "HTTP 503 service unavailable"
                for symbol in symbols
            }

    class Fallback:
        def __init__(self):
            self.calls = 0

        def batch_candles_with_errors(
            self,
            symbols,
            period="1y",
            interval="1d",
        ):
            self.calls += 1
            return {
                symbol: _frame(200)
                for symbol in symbols
            }, {}

    primary = Primary()
    fallback = Fallback()
    routed = RoutedMarketDataProvider(
        [primary, fallback],
        failure_threshold=2,
        cooldown_seconds=120,
    )

    for symbol in ("AAA", "BBB"):
        results, failures = routed.batch_candles_with_errors([symbol])
        assert failures == {}
        assert set(results) == {symbol}

    assert primary.calls == 2
    assert routed.health()["circuit_breakers"]["Primary"]["state"] == "open"

    routed.begin_observation()
    results, failures = routed.batch_candles_with_errors(["CCC"])

    assert failures == {}
    assert set(results) == {"CCC"}
    assert primary.calls == 2
    assert fallback.calls == 3

    snapshot = routed.observability_snapshot(["CCC"])
    assert snapshot["circuit_skip_count"] == 1
    assert snapshot["circuit_breakers"]["Primary"]["state"] == "open"
    assert any(
        event["event"] == "skipped_open_circuit"
        and event["provider"] == "Primary"
        for event in snapshot["circuit_events"]
    )


def test_routed_nse_resolver_stops_after_systemic_failure_budget():
    class Primary:
        def batch_candles_with_errors(
            self,
            symbols,
            period="1y",
            interval="1d",
        ):
            return {}, {
                symbol: "instrument not found"
                for symbol in symbols
            }

    class Resolver:
        def __init__(self):
            self.calls = []

        def health(self):
            return {
                "status": "configured",
                "runtime_status": "configured",
                "retry_after_seconds": 0,
            }

        def resolve_equity_symbol(self, symbol):
            self.calls.append(symbol)
            raise RuntimeError("connection timeout")

    class Fallback:
        def batch_candles_with_errors(
            self,
            symbols,
            period="1y",
            interval="1d",
        ):
            return {
                symbol: _frame(300)
                for symbol in symbols
            }, {}

    resolver = Resolver()
    routed = RoutedMarketDataProvider(
        [Primary(), Fallback()],
        symbol_resolver=resolver,
    )

    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    results, failures = routed.batch_candles_with_errors(symbols)

    assert failures == {}
    assert set(results) == set(symbols)
    assert resolver.calls == ["AAA", "BBB"]

    snapshot = routed.observability_snapshot(symbols)
    assert snapshot["nse_resolver_attempts"] == 2
    assert snapshot["nse_resolver_skips"] == 3
    assert any(
        event["event"] == "resolver_failure_budget_exhausted"
        for event in snapshot["circuit_events"]
    )


def test_yahoo_rate_limit_enters_cooldown_without_retry_storm(monkeypatch):
    import providers.yfinance_provider as yahoo_module

    provider = object.__new__(YahooFinanceProvider)
    YahooFinanceProvider.__init__(provider)

    calls = []

    def fail_download(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("Too Many Requests HTTP 429")

    monkeypatch.setattr(yahoo_module.yf, "download", fail_download)
    monkeypatch.setattr(
        yahoo_module.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(
            AssertionError("rate-limit errors must not retry")
        ),
    )

    with pytest.raises(RuntimeError, match="Too Many Requests"):
        provider.download(["AAA"])

    assert len(calls) == 1
    health = provider.health()
    assert health["status"] == "degraded"
    assert health["runtime_status"] == "rate_limited"
    assert health["retry_after_seconds"] > 0

    with pytest.raises(RuntimeError, match="cooldown active"):
        provider.download(["AAA"])

    assert len(calls) == 1


def test_nse_resolver_checks_cooldown_before_pacing(monkeypatch):
    provider = object.__new__(NSEProvider)
    NSEProvider.__init__(provider)
    provider._rate_limited_until = __import__("time").time() + 120

    monkeypatch.setattr(
        provider,
        "_pace_symbol_resolution",
        lambda: (_ for _ in ()).throw(
            AssertionError("pacing must not run during cooldown")
        ),
    )

    with pytest.raises(RuntimeError, match="cooldown active"):
        provider.resolve_equity_symbol("ABC")
