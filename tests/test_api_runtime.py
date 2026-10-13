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
    def __init__(self, symbol, name=""):
        self.symbol = symbol
        self.name = name


class FakeNifty500Universe:
    def __init__(self, count=500):
        self.members = [
            FakeUniverseMember(f"SYM{i}")
            for i in range(count)
        ]
        self.refresh_calls = []

    def ensure_loaded(self, refresh=False):
        self.refresh_calls.append(refresh)
        return list(self.members)

    def report(self, include_members=False):
        payload = {
            "status": "healthy",
            "index": "NIFTY 500",
            "nominal_company_count": 500,
            "minimum_security_count": 500,
            "maximum_security_count": 525,
            "expected_count": 500,
            "count": len(self.members),
            "security_count": len(self.members),
            "count_variance": len(self.members) - 500,
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
    assert len(body["symbol_results"]) == 50
    assert "rejected" not in body
    assert body["scale_gate"]["stage_limit"] == 50
    assert body["scale_gate"]["full_universe"] is False
    symbols, kwargs = scanner.calls[0]
    assert symbols == [f"SYM{i}" for i in range(50)]
    assert kwargs["batch_size"] == 20
    assert kwargs["batch_pause_seconds"] == 0
    assert kwargs["top_n"] == 5


def test_nifty500_scale_endpoint_marks_500_stage_as_full_universe_when_source_has_500():
    universe = FakeNifty500Universe(500)
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


def test_nifty500_scale_endpoint_can_return_full_payload_when_requested():
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
            "limit": 25,
            "batch_size": 25,
            "batch_pause_seconds": 0,
            "compact": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "rejected" in body
    assert len(body["rejected"]) == 25
    assert "symbol_results" not in body


def test_nifty500_scale_endpoint_does_not_call_500_full_when_source_has_501():
    universe = FakeNifty500Universe(501)
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
    assert gate["source_security_count"] == 501
    assert gate["nominal_company_count"] == 500
    assert gate["full_universe"] is False


def test_nifty500_scale_endpoint_full_universe_scans_all_501_source_securities():
    universe = FakeNifty500Universe(501)
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
            "full_universe": True,
            "batch_size": 25,
            "batch_pause_seconds": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scanned_count"] == 501
    assert len(body["symbol_results"]) == 501
    gate = body["scale_gate"]
    assert gate["stage_limit"] == 501
    assert gate["source_security_count"] == 501
    assert gate["nominal_company_count"] == 500
    assert gate["full_universe"] is True

    symbols, _ = scanner.calls[0]
    assert len(symbols) == 501
    assert symbols[-1] == "SYM500"


def test_nifty500_compact_response_serializes_signal_object_name():
    class SignalLike:
        def __init__(self):
            self.signal = "HOLD"
            self.overall_score = 12.5

    universe = FakeNifty500Universe()

    class Scanner:
        def scan_universe(self, symbols, **kwargs):
            symbol = symbols[0]
            return {
                "results": [],
                "rejected": [
                    {
                        "symbol": symbol,
                        "signal": SignalLike(),
                        "eligible": False,
                        "ranking_score": 12.5,
                        "rejection_reason": "negative_signal:hold",
                        "enrichment_failures": [],
                        "execution_errors": [],
                    }
                ],
                "scanned_count": 1,
                "count": 0,
                "rejected_count": 1,
                "top_picks": [],
                "scale_gate": {
                    "requested_symbols": 1,
                    "unique_symbols": 1,
                    "accounted_symbols": 1,
                    "completed_symbols": 1,
                    "error_symbols": 0,
                    "missing_symbols": 0,
                },
            }

    class Factory:
        def nifty500_universe(self):
            return universe

        def scanner_service(self):
            return Scanner()

    client = TestClient(create_app(Factory()))
    response = client.post(
        "/scan/universe/nifty500",
        json={
            "limit": 1,
            "batch_size": 1,
            "batch_pause_seconds": 0,
            "compact": True,
        },
    )

    assert response.status_code == 200
    rows = response.json()["symbol_results"]
    assert rows[0]["signal"] == "HOLD"


def test_nifty500_scale_excludes_nse_dummy_placeholder_from_tradable_limit():
    universe = FakeNifty500Universe(251)
    universe.members[100] = FakeUniverseMember(
        "DUMMYHEG",
        "DUMMY HEG LTD.",
    )
    scanner = FakeUniverseScanner()

    class Factory:
        def nifty500_universe(self):
            return universe

        def scanner_service(self):
            return scanner

    response = TestClient(create_app(Factory())).post(
        "/scan/universe/nifty500",
        json={
            "limit": 250,
            "batch_size": 25,
            "batch_pause_seconds": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    gate = body["scale_gate"]
    assert gate["stage_limit"] == 250
    assert gate["source_security_count"] == 251
    assert gate["tradable_security_count"] == 250
    assert gate["excluded_index_placeholders"] == ["DUMMYHEG"]
    assert gate["excluded_index_placeholder_count"] == 1

    symbols, _ = scanner.calls[0]
    assert len(symbols) == 250
    assert "DUMMYHEG" not in symbols


def test_scan_runtime_endpoint_reports_active_universe_scan():
    app = create_app(
        FakeApplication(),
        database_initializer=lambda: {"status": "initialized"},
    )
    guard = app.state.scan_execution_guard

    idle = TestClient(app).get("/observability/scan-runtime")
    assert idle.status_code == 200
    assert idle.json()["status"] == "idle"

    assert guard.try_start("existing-run") is True
    guard.annotate(
        "existing-run",
        limit=500,
        full_universe=True,
        batch_size=25,
    )

    busy = TestClient(app).get("/observability/scan-runtime")
    assert busy.status_code == 200
    body = busy.json()
    assert body["status"] == "busy"
    assert body["active"]["run_id"] == "existing-run"
    assert body["active"]["full_universe"] is True

    guard.finish("existing-run", "completed")


def test_nifty500_scan_rejects_overlap_with_409_and_active_run():
    app = create_app(
        FakeApplication(),
        database_initializer=lambda: {"status": "initialized"},
    )
    guard = app.state.scan_execution_guard
    assert guard.try_start("existing-run") is True

    response = TestClient(app).post(
        "/scan/universe/nifty500?run_id=new-run",
        json={
            "limit": 25,
            "batch_size": 25,
            "batch_pause_seconds": 0,
        },
    )

    assert response.status_code == 409
    assert response.headers["retry-after"] == "15"
    detail = response.json()["detail"]
    assert "already running" in detail["message"]
    assert detail["active"]["run_id"] == "existing-run"

    guard.finish("existing-run", "completed")
