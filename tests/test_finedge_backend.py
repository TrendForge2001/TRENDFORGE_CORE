from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi.testclient import TestClient
import pytest

from api.app import create_app
from providers.finedge_api_provider import FinEdgeAPIProvider, FinEdgeError
from services.finedge_fundamental_service import FinEdgeFundamentalService


class Response:
    headers = {}

    def __init__(self, code=200, body=None):
        self.status_code = code
        self.body = body if body is not None else {"data": [{"source_metric": 18, "period": "FY2026"}]}

    def json(self):
        return self.body


class Session:
    def __init__(self):
        self.calls = []
        self.response = Response()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _service(**kwargs):
    session = Session()
    provider = FinEdgeAPIProvider(api_key="finedge-backend-fixture-key", enabled=True, session=session)
    return FinEdgeFundamentalService(provider, **kwargs), session


def test_cache_statement_isolation_expiry_and_force():
    now = [0.0]
    service, session = _service(clock=lambda: now[0], cache_ttl_seconds=100)
    first = service.fetch("itc")
    assert len(session.calls) == 4
    assert first["cache"]["hit"] is False
    first["symbols"][0]["symbol"] = "MUTATED"
    cached = service.fetch("ITC")
    assert len(session.calls) == 4
    assert cached["cache"]["hit"] is True
    assert cached["api_calls"] == 0
    assert cached["symbols"][0]["symbol"] == "ITC"
    assert cached["symbols"][0]["verified_for_scanner"] is False
    service.fetch("ITC", statement_type="s")
    assert len(session.calls) == 8
    service.fetch("ITC", force_refresh=True)
    assert len(session.calls) == 12
    now[0] = 101
    service.fetch("ITC")
    assert len(session.calls) == 16


def test_concurrent_requests_coalesce_cache_miss():
    service, session = _service()
    with ThreadPoolExecutor(max_workers=8) as pool:
        reports = list(pool.map(lambda _: service.fetch("RELIANCE"), range(8)))
    assert len(session.calls) == 4
    assert sum(not report["cache"]["hit"] for report in reports) == 1


def test_failed_response_is_not_cached():
    service, session = _service()
    session.response = Response(403)
    with pytest.raises(FinEdgeError):
        service.fetch("ITC")
    session.response = Response()
    result = service.fetch("ITC")
    assert result["cache"]["hit"] is False
    assert len(session.calls) == 5


def test_same_key_different_caps_share_conservative_budget():
    first = FinEdgeAPIProvider(api_key="quota-sharing-fixture", calls_per_minute=300)
    second = FinEdgeAPIProvider(api_key="quota-sharing-fixture", calls_per_minute=280)
    assert first.limiter is second.limiter
    assert first.limiter.health()["max_calls_per_minute"] == 280


def test_env_key_enables_provider_with_headroom(monkeypatch):
    monkeypatch.setenv("FINEDGE_API_KEY", "env-fixture")
    monkeypatch.delenv("FINEDGE_ENABLED", raising=False)
    monkeypatch.delenv("FINEDGE_RATE_LIMIT_PER_MINUTE", raising=False)
    provider = FinEdgeAPIProvider.from_env()
    assert provider.enabled is True
    assert provider.calls_per_minute == 280
    monkeypatch.setenv("FINEDGE_ENABLED", "false")
    assert FinEdgeAPIProvider.from_env().enabled is False


def test_readiness_and_requests_are_authenticated_and_secret_free(monkeypatch):
    service, session = _service()

    class Factory:
        def finedge_fundamental_service(self):
            return service

    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "k" * 40)
    client = TestClient(create_app(Factory()))
    assert client.get("/fundamentals/finedge/readiness").status_code == 401
    assert client.post("/fundamentals/finedge/fetch", json={"symbol": "ITC"}).status_code == 401
    assert session.calls == []
    headers = {"X-TrendForge-Admin-Key": "k" * 40}
    readiness = client.get("/fundamentals/finedge/readiness", headers=headers)
    assert readiness.status_code == 200
    assert session.calls == []
    assert "finedge-backend-fixture-key" not in readiness.text
    result = client.post("/fundamentals/finedge/fetch", json={"symbol": "itc"}, headers=headers)
    assert result.status_code == 200
    assert result.json()["symbols"][0]["symbol"] == "ITC"
    assert len(session.calls) == 4
    assert "finedge-backend-fixture-key" not in result.text
    invalid = client.post("/fundamentals/finedge/fetch", json={"symbol": "../invalid"}, headers=headers)
    assert invalid.status_code == 422
    assert len(session.calls) == 4


def test_upstream_error_body_is_not_exposed_or_cached():
    service, session = _service()
    session.response = Response(body={"success": False, "error": "secret-sentinel"})
    with pytest.raises(FinEdgeError) as error:
        service.fetch("ITC")
    assert "secret-sentinel" not in str(error.value)
    assert not service._cache


def test_waiting_limiter_does_not_block_cooldown_or_health():
    from providers.finedge_api_provider import SlidingWindowRateLimiter

    now = [0.0]
    waiting = threading.Event()
    release = threading.Event()

    def sleep(seconds):
        waiting.set()
        assert release.wait(3)
        now[0] += seconds

    limiter = SlidingWindowRateLimiter(1, clock=lambda: now[0], sleep=sleep)
    limiter.acquire()
    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(limiter.acquire)
        try:
            assert waiting.wait(1)
            health = pool.submit(limiter.health).result(timeout=1)
            assert health["recent_reserved_calls"] == 1
            pool.submit(limiter.cooldown, 10).result(timeout=1)
        finally:
            release.set()
        worker.result(timeout=2)
