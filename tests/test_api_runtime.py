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


class FakeUniverseMember:
    def __init__(self, symbol):
        self.symbol = symbol


class FakeNifty500Universe:
    def __init__(self):
        self.members = [
            FakeUniverseMember(f"SYM{i}")
            for i in range(500)
        ]
        self.refresh_calls = []

    def ensure_loaded(self, refresh=False):
        self.refresh_calls.append(refresh)
        return list(self.members)

    def report(self, include_members=False):
        payload = {
            "status": "healthy",
            "index": "NIFTY 500",
            "expected_count": 500,
            "count": 500,
            "source": "NSE_NIFTY500_CSV",
        }
        if include_members:
            payload["members"] = [
                {"symbol": member.symbol}
                for member in self.members
            ]
        return payload


class FakeUniverseScanner:
    def __init__(self):
        self.calls = []

    def scan_universe(self, symbols, **kwargs):
        self.calls.append((list(symbols), dict(kwargs)))
        return {
            "results": [],
            "rejected": [
                {
                    "symbol": symbol,
                    "signal": "HOLD",
                    "passed": False,
                }
                for symbol in symbols
            ],
            "scanned_count": len(symbols),
            "count": 0,
            "rejected_count": len(symbols),
            "top_picks": [],
            "scale_gate": {
                "requested_symbols": len(symbols),
                "unique_symbols": len(symbols),
                "accounted_symbols": len(symbols),
                "completed_symbols": len(symbols),
                "error_symbols": 0,
                "missing_symbols": 0,
            },
        }


def test_nifty500_universe_endpoint_exposes_source_backed_members():
    universe = FakeNifty500Universe()

    class Factory:
        def nifty500_universe(self):
            return universe

    client = TestClient(create_app(Factory()))
    response = client.get(
        "/universe/nifty500?refresh=true&include_members=true"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["count"] == 500
    assert body["source"] == "NSE_NIFTY500_CSV"
    assert len(body["members"]) == 500
    assert universe.refresh_calls == [True]


def test_nifty500_scale_endpoint_uses_stage_limit_and_batch_size():
    universe = FakeNifty500Universe()
    scanner = FakeUniverseScanner()

    class Factory:
        def nifty500_universe(self):
            return universe

        def scanner_service(self):
            return scanner

    client = TestClient(create_app(Factory()))
    response = client.post(
        "/scan/universe/nifty500",
        json={
            "limit": 50,
            "batch_size": 20,
            "batch_pause_seconds": 0,
            "top_n": 5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scanned_count"] == 50
    assert body["universe"]["count"] == 500
    assert body["scale_gate"]["stage_limit"] == 50
    assert body["scale_gate"]["full_universe"] is False
    symbols, kwargs = scanner.calls[0]
    assert symbols == [f"SYM{i}" for i in range(50)]
    assert kwargs["batch_size"] == 20
    assert kwargs["batch_pause_seconds"] == 0
    assert kwargs["top_n"] == 5


def test_nifty500_scale_endpoint_marks_500_stage_as_full_universe():
    universe = FakeNifty500Universe()
    scanner = FakeUniverseScanner()

    class Factory:
        def nifty500_universe(self):
            return universe

        def scanner_service(self):
            return scanner

    client = TestClient(create_app(Factory()))
    response = client.post(
        "/scan/universe/nifty500",
        json={
            "limit": 500,
            "batch_size": 25,
            "batch_pause_seconds": 0,
        },
    )

    assert response.status_code == 200
    gate = response.json()["scale_gate"]
    assert gate["stage_limit"] == 500
    assert gate["full_universe"] is True


def test_nifty500_scale_endpoint_refuses_degraded_universe():
    class DegradedUniverse(FakeNifty500Universe):
        def report(self, include_members=False):
            return {
                "status": "degraded",
                "expected_count": 500,
                "count": 499,
            }

    class Factory:
        def nifty500_universe(self):
            return DegradedUniverse()

        def scanner_service(self):
            raise AssertionError("scanner must not execute")

    client = TestClient(create_app(Factory()))
    response = client.post(
        "/scan/universe/nifty500",
        json={"limit": 25},
    )

    assert response.status_code == 503
    assert "not healthy" in response.json()["detail"]
