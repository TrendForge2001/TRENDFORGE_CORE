"""Offline contract tests for the opt-in FinEdge API transport."""
from __future__ import annotations

import json

import pytest
import requests

from providers.finedge_api_provider import (
    FinEdgeAPIProvider, FinEdgeError, SlidingWindowRateLimiter,
)
from scripts.finedge_fundamental_candidates import (
    collect_candidates, exclusive_json_write, normalize_symbols,
)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Response:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.payload = payload if payload is not None else {"data": []}

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [Response()])

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses[min(len(self.calls)-1, len(self.responses)-1)]


def test_inactive_provider_fails_closed_with_no_network(monkeypatch):
    session = Session()
    client = FinEdgeAPIProvider(api_key="secret-key", session=session)
    assert client.health()["status"] == "disabled"
    with pytest.raises(FinEdgeError, match="disabled or not configured"):
        client.ratios("TCS")
    assert session.calls == []
    monkeypatch.setenv("FINEDGE_ENABLED", "true")
    monkeypatch.delenv("FINEDGE_API_KEY", raising=False)
    assert FinEdgeAPIProvider.from_env().health()["status"] == "not_configured"


def test_300_calls_per_minute_in_rolling_window():
    clock = Clock()
    limiter = SlidingWindowRateLimiter(
        300, clock=clock.monotonic, sleep=clock.sleep
    )
    for _ in range(300):
        limiter.acquire()
    assert clock.now == 0.0
    assert limiter.health()["recent_reserved_calls"] == 300
    limiter.acquire()
    assert clock.now >= 60.0
    assert len(clock.sleeps) == 1
    assert limiter.health()["recent_reserved_calls"] == 1


def test_configured_ceiling_never_exceeds_300():
    assert SlidingWindowRateLimiter(999).limit == 300
    assert SlidingWindowRateLimiter(1).limit == 1
    assert FinEdgeAPIProvider(
        api_key="key", enabled=True, calls_per_minute=999
    ).health()["rate_limit"]["max_calls_per_minute"] == 300


def test_query_token_is_used_only_in_transport_and_no_redirect():
    session = Session([Response(payload={"items": [1]})])
    client = FinEdgeAPIProvider(api_key="never-print-me", enabled=True, session=session)
    assert client.ratios("TCS", ratio_type="pr") == {"items": [1]}
    url, options = session.calls[0]
    assert url == "https://data.finedgeapi.com/api/v1/ratios/TCS"
    assert options["params"]["token"] == "never-print-me"
    assert options["params"]["ratio_type"] == "pr"
    assert options["allow_redirects"] is False
    assert "never-print-me" not in json.dumps(client.health())


def test_429_cooldown_without_automatic_retry():
    clock = Clock()
    limiter = SlidingWindowRateLimiter(
        300, clock=clock.monotonic, sleep=clock.sleep
    )
    session = Session([Response(status=429, headers={"Retry-After": "25"})])
    client = FinEdgeAPIProvider(
        api_key="abc", enabled=True, session=session, limiter=limiter
    )
    with pytest.raises(FinEdgeError, match="429") as error:
        client.fetch("stock-symbols")
    assert error.value.status_code == 429
    assert len(session.calls) == 1
    assert limiter.health()["cooldown_seconds_remaining"] == 25.0
    limiter.acquire()
    assert clock.now == 25.0


def test_errors_do_not_expose_secret_or_urls():
    key = "super-secret-key"
    class Broken:
        def get(self, url, **kwargs):
            raise requests.exceptions.ConnectionError(
                f"https://data.finedgeapi.com/api/v1/ratios/TCS?token={key}"
            )
    client = FinEdgeAPIProvider(api_key=key, enabled=True, session=Broken())
    with pytest.raises(FinEdgeError) as error:
        client.ratios("TCS")
    assert key not in str(error.value)
    assert "https://" not in str(error.value)


def test_invalid_symbols_and_invalid_ratio_type_never_fetch():
    session = Session()
    client = FinEdgeAPIProvider(api_key="key", enabled=True, session=session)
    for sym in ["../secrets", "AAA/B", ""]:
        with pytest.raises(ValueError):
            client.ratios(sym)
    with pytest.raises(ValueError):
        client.ratios("TCS", ratio_type="bad")
    with pytest.raises(ValueError):
        client.fetch("unrecognized")
    with pytest.raises(ValueError):
        client.fetch("quote", params={"token": "injected"})
    assert not session.calls


def test_candidate_export_is_nonwriting_and_exclusive(tmp_path):
    class FakeFinEdge:
        NAME = "FinEdgeAPIProvider"
        def __init__(self):
            self.calls = 0

        def ratios(self, symbol, **kwargs):
            self.calls += 1
            return {"company": symbol, "periods": ["FY2026"]}

        def financial_metrics(self, symbol, **kwargs):
            self.calls += 1
            return {"company": symbol, "growth": 3.3}

        def shareholding_pattern(self, symbol, **kwargs):
            self.calls += 1
            return {"company": symbol, "promoter_pct": 40}

    fake = FakeFinEdge()
    symbols = normalize_symbols("ITC,RELIANCE,ITC")
    assert symbols == ["ITC", "RELIANCE"]
    payload = collect_candidates(fake, symbols)
    assert fake.calls == 8
    assert payload["api_calls"] == 8
    assert all(not item["verified_for_scanner"] for item in payload["symbols"])
    output = tmp_path / "finedge-unverified.json"
    exclusive_json_write(output, payload)
    assert json.loads(output.read_text())["schema_version"] == "R71.2-candidates-v1"
    with pytest.raises(FileExistsError):
        exclusive_json_write(output, payload)
    with pytest.raises(ValueError):
        normalize_symbols("BAD/SYMBOL")
    with pytest.raises(ValueError):
        normalize_symbols(",".join(f"SYM{i}" for i in range(26)))
