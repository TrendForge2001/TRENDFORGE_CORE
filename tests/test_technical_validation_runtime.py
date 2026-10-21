from __future__ import annotations

from types import SimpleNamespace
import threading
from concurrent.futures import ThreadPoolExecutor

from services import technical_validation_runtime as runtime


def test_validation_worker_captures_request_parameters(monkeypatch, tmp_path):
    calls = []

    class FakeValidationService:
        def __init__(self, *, technical_service):
            assert technical_service == "technical-service"

        def run(self, **kwargs):
            calls.append(kwargs)
            return {
                "completed_at": "2026-10-21T00:00:00+00:00",
                "master_symbol_count": 0,
                "aggregate": [],
                "errors": [],
            }

    monkeypatch.setattr(runtime, "TechnicalValidationService", FakeValidationService)
    monkeypatch.setenv(
        "TRENDFORGE_R715_OUTPUT_PATH",
        str(tmp_path / "validation.json"),
    )
    monkeypatch.setenv("TRENDFORGE_R715_CAPITAL", "999")
    monkeypatch.setenv("TRENDFORGE_R715_CHUNK_SIZE", "2")

    app = SimpleNamespace(state=SimpleNamespace())
    started = runtime.start_validation(
        app,
        technical_service="technical-service",
        capital=123456,
        chunk_size=17,
        force=True,
    )
    app.state.r715_validation["_thread"].join(timeout=5)

    assert started["capital"] == 123456.0
    assert started["chunk_size"] == 17
    assert calls[0]["capital"] == 123456.0
    assert calls[0]["chunk_size"] == 17
    assert app.state.r715_validation["status"] == "completed"


def test_concurrent_and_forced_requests_share_one_worker(monkeypatch, tmp_path):
    release = threading.Event()
    entered = threading.Event()
    calls = []

    class Service:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            calls.append(kwargs)
            entered.set()
            assert release.wait(5)
            return {"errors": [], "aggregate": []}

    monkeypatch.setattr(runtime, "TechnicalValidationService", Service)
    monkeypatch.setenv("TRENDFORGE_R715_OUTPUT_PATH", str(tmp_path / "result.json"))
    app = SimpleNamespace(state=SimpleNamespace())
    first = runtime.start_validation(app, technical_service=object(), capital=123456, chunk_size=17)
    worker = app.state.r715_validation["_thread"]
    try:
        assert entered.wait(2)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(
                lambda _: runtime.start_validation(app, technical_service=object(), capital=900000, force=True),
                range(8),
            ))
        assert all(result["run_id"] == first["run_id"] for result in results)
        assert len(calls) == 1
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert app.state.r715_validation["status"] == "completed"
    assert app.state.r715_validation["capital"] == 123456
    assert app.state.r715_validation["_thread"] is worker


def test_export_uses_admin_header_and_json_contract(monkeypatch, tmp_path):
    from api.app import create_app
    from fastapi.testclient import TestClient

    output = tmp_path / "result.json"
    output.write_text('{"status":"completed"}', encoding="utf-8")
    monkeypatch.setenv("TRENDFORGE_R715_OUTPUT_PATH", str(output))
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "k" * 40)
    client = TestClient(create_app(SimpleNamespace()))
    assert client.get("/technical/validation/export?token=old-token").status_code == 401
    response = client.get("/technical/validation/export", headers={"X-TrendForge-Admin-Key": "k" * 40})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json()["status"] == "completed"


def test_multi_strategy_concurrent_requests_share_worker(monkeypatch, tmp_path):
    from services import multi_strategy_validation_runtime as multi

    release = threading.Event()
    entered = threading.Event()
    calls = []

    class Service:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            calls.append(kwargs)
            entered.set()
            assert release.wait(5)
            return {"errors": []}

    monkeypatch.setattr(multi, "MultiStrategyValidationService", Service)
    monkeypatch.setattr(multi, "_persistent_validation", lambda: None)
    monkeypatch.setattr(multi, "_persist_validation", lambda _: None)
    monkeypatch.setenv("TRENDFORGE_R7253_OUTPUT_PATH", str(tmp_path / "multi.json"))
    app = SimpleNamespace(state=SimpleNamespace())
    first = multi.start_validation(app, scanner_service=object(), request={})
    worker = app.state.r7253_validation["_thread"]
    try:
        assert entered.wait(2)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(
                lambda _: multi.start_validation(app, scanner_service=object(), request={"force": True}),
                range(8),
            ))
        assert all(result["run_id"] == first["run_id"] for result in results)
        assert len(calls) == 1
    finally:
        release.set()
        worker.join(5)
    assert app.state.r7253_validation["status"] == "completed"
    assert app.state.r7253_validation["_thread"] is worker
