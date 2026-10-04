from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class FakeApplication:
    def health(self):
        return {
            "status": "healthy",
            "configuration": {"status": "ok"},
            "market_data": {"status": "ok"},
            "enrichment": {"status": "not_configured"},
            "scanner": {"status": "healthy"},
            "domain_providers": {
                "news": "FakeNewsProvider",
                "corporate_actions": "FakeCorporateActionProvider",
            },
        }


def test_create_app_injects_application_factory():
    application = FakeApplication()
    app = create_app(application)

    assert app.state.application_factory is application


def test_create_app_builds_and_exposes_default_factory():
    app = create_app()

    assert app.state.application_factory is not None


def test_root_endpoint_is_boot_safe():
    app = create_app(FakeApplication(), database_initializer=lambda: {"status": "initialized"})

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.json() == {"service": "TrendForge Core", "status": "ok"}


def test_health_endpoint_uses_injected_application_factory():
    app = create_app(FakeApplication(), database_initializer=lambda: {"status": "initialized"})

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert "configuration" in response.json()


def test_health_endpoint_converts_runtime_failure_to_503():
    class BrokenApplication:
        def health(self):
            raise RuntimeError("provider unavailable")

    app = create_app(BrokenApplication())

    response = TestClient(app).get("/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "provider unavailable"


def test_scan_validation_rejects_empty_symbol_list_before_pipeline_execution():
    app = create_app(FakeApplication())

    response = TestClient(app).post("/scan", json={"symbols": []})

    assert response.status_code == 422


def test_scan_validation_rejects_more_than_nifty_500_symbols():
    app = create_app(FakeApplication())
    response = TestClient(app).post(
        "/scan",
        json={"symbols": [f"SYM{i}" for i in range(501)]},
    )
    assert response.status_code == 422


def test_scan_validation_rejects_blank_symbol_values():
    app = create_app(FakeApplication())
    response = TestClient(app).post(
        "/scan",
        json={"symbols": ["AAA", "   "]},
    )
    assert response.status_code == 422


def test_scan_request_normalizes_symbols_before_service_execution():
    calls = []

    class Scanner:
        def scan_many(self, symbols, **kwargs):
            calls.append(symbols)
            return {"scanned_count": len(symbols), "top_picks": []}

    class Factory:
        def scanner_service(self):
            return Scanner()

    app = create_app(Factory())
    response = TestClient(app).post(
        "/scan",
        json={"symbols": [" aaa ", "BbB"]},
    )

    assert response.status_code == 200
    assert calls == [["AAA", "BBB"]]


def test_scan_validation_rejects_duplicate_symbols_after_normalization():
    class Scanner:
        def scan_many(self, symbols, **kwargs):
            assert symbols == ["AAA", "AAA"]
            return {"scanned_count": 2, "top_picks": []}

    class Factory:
        def scanner_service(self):
            return Scanner()

    app = create_app(Factory())
    response = TestClient(app).post(
        "/scan",
        json={"symbols": ["aaa", " AAA "]},
    )
    assert response.status_code == 200


def test_scan_symbol_rejects_blank_path_symbol():
    app = create_app(FakeApplication())
    response = TestClient(app).get("/scan/%20")
    assert response.status_code == 422
    assert response.json()["detail"] == "Symbol is required"


def test_scan_symbol_normalizes_path_symbol():
    calls = []

    class Scanner:
        def scan(self, symbol, **kwargs):
            calls.append(symbol)
            return {"symbol": symbol, "signal": "BUY"}

    class Factory:
        def scanner_service(self):
            return Scanner()

    app = create_app(Factory())
    response = TestClient(app).get("/scan/%20abc%20")
    assert response.status_code == 200
    assert calls == ["ABC"]
