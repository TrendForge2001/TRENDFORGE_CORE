"""Runtime diagnostics retain correlation without retaining provider secrets."""
from __future__ import annotations

import json
import re

import pytest

from api.scanner_service import ScannerService
from core.application_factory import ApplicationFactory


SENTINEL = "query-token-runtime-sentinel"


class _Provider:
    def candles(self, *args, **kwargs):
        raise AssertionError("Diagnostics must not fetch candles")


class _Orchestrator:
    def health(self):
        return {"status": "configured"}


class _FailingPipeline:
    orchestrator = _Orchestrator()
    fail = True

    def analyze(self, symbol, **kwargs):
        if self.fail:
            raise RuntimeError(f"https://provider.invalid/data?token={SENTINEL}")
        return {"symbol": symbol, "signal": "HOLD"}


def test_scanner_failure_health_and_logs_do_not_retain_exception_text(caplog):
    service = ScannerService(_FailingPipeline())

    with pytest.raises(RuntimeError, match=SENTINEL):
        service.scan("ABC")

    report = service.health()
    assert report["runtime_status"] == "failed"
    reference = report["last_error_reference"]
    assert re.fullmatch(r"[a-f0-9]{12}", reference)
    assert reference in caplog.text
    assert SENTINEL not in json.dumps(report)
    assert SENTINEL not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_scanner_success_clears_previous_failure_reference():
    pipeline = _FailingPipeline()
    service = ScannerService(pipeline)
    with pytest.raises(RuntimeError):
        service.scan("ABC")

    pipeline.fail = False
    service.scan("ABC")

    report = service.health()
    assert report["runtime_status"] == "runtime_verified"
    assert report["last_error"] is None
    assert report["last_error_reference"] is None


def test_failed_configured_import_does_not_expose_input_path_or_error(monkeypatch, caplog):
    from config import settings

    monkeypatch.setattr(settings, "FUNDAMENTALS_IMPORT_PATH", f"/private/{SENTINEL}.json")
    factory = ApplicationFactory(kite=_Provider(), yahoo=_Provider())

    class _Manager:
        def import_file(self, *args, **kwargs):
            raise RuntimeError(f"Invalid credential: {SENTINEL}")

    monkeypatch.setattr(factory, "fundamental_manager", lambda: _Manager())
    report = factory.import_fundamentals_if_configured()

    assert report["status"] == "failed"
    assert report["error_code"] == "FUNDAMENTALS_IMPORT_FAILED"
    assert report["reference"] in caplog.text
    assert SENTINEL not in json.dumps(report)
    assert SENTINEL not in json.dumps(factory.health()["fundamental_import"])
    assert SENTINEL not in caplog.text


def test_failed_enrichment_snapshot_does_not_expose_input_path_or_error(monkeypatch, caplog):
    def fail_snapshot(*args, **kwargs):
        raise RuntimeError(f"Invalid credential: {SENTINEL}")

    monkeypatch.setenv("ENRICHMENT_SNAPSHOT_PATH", f"/private/{SENTINEL}.json")
    monkeypatch.setattr("providers.enrichment_snapshot_provider.EnrichmentSnapshot", fail_snapshot)
    factory = ApplicationFactory(kite=_Provider(), yahoo=_Provider())

    report = factory.health()["enrichment_snapshot"]
    assert report["status"] == "failed"
    assert report["error_code"] == "ENRICHMENT_SNAPSHOT_UNAVAILABLE"
    assert report["reference"] in caplog.text
    assert SENTINEL not in json.dumps(report)
    assert SENTINEL not in caplog.text
