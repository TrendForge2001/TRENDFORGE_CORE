"""NSE constituent fallbacks are safe and coalesce concurrent refresh work."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from types import SimpleNamespace
import threading

import pytest

from providers.nse_broad_market_constituents import NSEBroadMarketConstituentProvider

SECRET = "SENTINEL_TOKEN_MUST_NOT_APPEAR"


class Session:
    def __init__(self, *, count=100, fail=False):
        self.headers = {}
        self.calls = []
        self.fail = fail
        self.count = count
        self.entered = None
        self.release = None

    def get(self, url, **kwargs):
        self.calls.append(url)
        if self.entered is not None:
            self.entered.set()
            assert self.release.wait(3.0)
        if self.fail:
            raise RuntimeError(f"https://nse.invalid/private?token={SECRET}")
        csv = "Company Name,Industry,Symbol\n" + "".join(
            f"Company {i},Industry,S{i:03d}\n" for i in range(self.count)
        )
        return SimpleNamespace(
            text=csv,
            headers={"content-type": "text/csv"},
            raise_for_status=lambda: None,
        )


def test_package_fallback_health_and_logs_never_contain_exception_text(tmp_path, caplog):
    session = Session(fail=True)
    provider = NSEBroadMarketConstituentProvider(session=session, cache_dir=tmp_path)

    with caplog.at_level(logging.WARNING, logger="trendforge.nse.constituents"):
        payload = provider.load("NIFTY 100")
        cached = provider.load("100")

    health = provider.health()["indexes"]["NIFTY 100"]
    reference = health["last_error_reference"]
    assert len(reference) == 12
    assert payload == cached
    assert payload["stale"] is True
    assert payload["snapshot_storage"] == "package"
    assert payload["snapshot_as_of"] in payload["source_warning"]
    assert reference in payload["source_warning"]
    assert health["last_error"] == "NSE constituent refresh temporarily unavailable"
    assert health["status"] == "degraded"
    assert len(session.calls) == 2
    assert len(caplog.records) == 1
    assert reference in caplog.text
    assert SECRET not in json.dumps(payload)
    assert SECRET not in json.dumps(provider.health())
    assert SECRET not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("saved_on_disk", [False, True])
def test_validated_cache_fallback_warning_is_safe(tmp_path, saved_on_disk):
    session = Session()
    provider = NSEBroadMarketConstituentProvider(session=session, cache_dir=tmp_path)
    fresh = provider.load("NIFTY 100")
    if saved_on_disk:
        provider = NSEBroadMarketConstituentProvider(session=session, cache_dir=tmp_path)
    session.fail = True

    stale = provider.load("NIFTY 100", force_refresh=True)

    assert stale["members"] == fresh["members"]
    assert stale["stale"] is True
    assert "last validated NIFTY 100" in stale["source_warning"]
    assert SECRET not in json.dumps(stale)
    assert SECRET not in json.dumps(provider.health())


def test_uncached_failure_cooldown_is_safe_and_recovers(tmp_path, caplog):
    session = Session(count=200, fail=True)
    provider = NSEBroadMarketConstituentProvider(session=session, cache_dir=tmp_path)

    with caplog.at_level(logging.WARNING, logger="trendforge.nse.constituents"):
        with pytest.raises(RuntimeError) as first:
            provider.load("NIFTY 200")
        with pytest.raises(RuntimeError) as second:
            provider.load("200")

    assert len(session.calls) == 2  # One attempt for each official source.
    assert str(first.value) == str(second.value)
    assert SECRET not in str(first.value)
    assert SECRET not in caplog.text
    assert len(caplog.records) == 1
    assert provider.health()["indexes"]["NIFTY 200"]["last_error_reference"] in str(first.value)

    provider._failure_retry_after["NIFTY 200"] = 0.0
    session.fail = False
    assert provider.load("NIFTY 200")["count"] == 200
    assert len(session.calls) == 3
    recovered = provider.health()["indexes"]["NIFTY 200"]
    assert recovered["status"] == "runtime_verified"
    assert recovered["last_error"] is None
    assert recovered["last_error_reference"] is None


@pytest.mark.parametrize("fail", [False, True])
def test_concurrent_cold_reads_share_success_or_failure(tmp_path, fail):
    session = Session(count=200, fail=fail)
    session.entered = threading.Event()
    session.release = threading.Event()
    provider = NSEBroadMarketConstituentProvider(session=session, cache_dir=tmp_path)

    def read():
        try:
            return provider.load("NIFTY 200")
        except RuntimeError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(read) for _ in range(8)]
        try:
            assert session.entered.wait(2.0)
        finally:
            session.release.set()
        results = [future.result(timeout=3.0) for future in futures]

    assert len(session.calls) == (2 if fail else 1)
    assert all(result == results[0] for result in results)
    assert SECRET not in json.dumps(results)

