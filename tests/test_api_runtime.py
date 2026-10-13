from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from database.repositories.scan_run_audit_repository import (
    DuplicateScanRunIdError,
)


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


class FakeAuditService:
    def __init__(self, records=None):
        self.records = {
            str(key): dict(value)
            for key, value in (records or {}).items()
        }

    def ensure_available(self, run_id):
        if str(run_id) in self.records:
            raise DuplicateScanRunIdError(
                f"scan run_id already exists: {run_id}"
            )

    def record(self, payload):
        run_id = str(payload["run_id"])
        if run_id in self.records:
            raise DuplicateScanRunIdError(
                f"scan run_id already exists: {run_id}"
            )
        self.records[run_id] = dict(payload)
        return dict(payload)

    def get(self, run_id):
        value = self.records.get(str(run_id))
        return dict(value) if value is not None else None

    def latest(self, limit=20):
        return [
            dict(value)
            for value in list(self.records.values())[-limit:]
        ]


def test_nifty500_completed_run_writes_completed_terminal_audit():
    universe = FakeNifty500Universe()
    scanner = FakeUniverseScanner()
    audit = FakeAuditService()

    class Factory:
        def nifty500_universe(self):
            return universe

        def scanner_service(self):
            return scanner

        def scan_run_audit_service(self):
            return audit

    app = create_app(Factory())
    response = TestClient(app).post(
        "/scan/universe/nifty500?run_id=completed-run",
        json={
            "limit": 25,
            "batch_size": 25,
            "batch_pause_seconds": 0,
        },
    )

    assert response.status_code == 200
    record = audit.get("completed-run")
    assert record["outcome"] == "completed"
    assert record["http_status"] == 200
    assert record["failure_stage"] is None
    assert record["failure_message"] is None
    assert record["requested_symbols"] == 25
    assert record["completed_symbols"] == 25


def test_nifty500_failed_run_writes_failed_terminal_audit_and_releases_guard():
    universe = FakeNifty500Universe()
    audit = FakeAuditService()

    class BrokenScanner:
        def scan_universe(self, symbols, **kwargs):
            raise RuntimeError("simulated scanner failure")

    class Factory:
        def nifty500_universe(self):
            return universe

        def scanner_service(self):
            return BrokenScanner()

        def scan_run_audit_service(self):
            return audit

    app = create_app(Factory())
    response = TestClient(app).post(
        "/scan/universe/nifty500?run_id=failed-run",
        json={
            "limit": 25,
            "batch_size": 25,
            "batch_pause_seconds": 0,
        },
    )

    assert response.status_code == 503
    record = audit.get("failed-run")
    assert record["outcome"] == "failed"
    assert record["http_status"] == 503
    assert record["failure_stage"] == "scan_execution"
    assert record["failure_message"] == "simulated scanner failure"
    assert record["requested_symbols"] == 25
    assert record["completed_symbols"] == 0
    assert record["error_details"]["fatal"] == "simulated scanner failure"

    runtime = app.state.scan_execution_guard.status()
    assert runtime["status"] == "idle"
    assert runtime["last_completed"]["run_id"] == "failed-run"
    assert runtime["last_completed"]["outcome"] == "failed"


def test_overlap_rejection_writes_rejected_audit_for_unique_run_id():
    audit = FakeAuditService()

    class Factory:
        def scan_run_audit_service(self):
            return audit

    app = create_app(Factory())
    guard = app.state.scan_execution_guard
    assert guard.try_start("primary-run") is True

    response = TestClient(app).post(
        "/scan/universe/nifty500?run_id=rejected-run",
        json={
            "limit": 25,
            "batch_size": 25,
            "batch_pause_seconds": 0,
        },
    )

    assert response.status_code == 409
    record = audit.get("rejected-run")
    assert record["outcome"] == "rejected"
    assert record["http_status"] == 409
    assert record["failure_stage"] == "admission"
    assert record["completed_symbols"] == 0
    assert record["metadata"]["active_run_id"] == "primary-run"

    guard.finish("primary-run", "completed")


def test_duplicate_historical_run_id_is_rejected_without_overwrite():
    original = {
        "run_id": "immutable-run",
        "outcome": "completed",
        "completed_symbols": 25,
    }
    audit = FakeAuditService({"immutable-run": original})

    class Factory:
        def scan_run_audit_service(self):
            return audit

        def nifty500_universe(self):
            raise AssertionError("duplicate run must not reach universe")

        def scanner_service(self):
            raise AssertionError("duplicate run must not reach scanner")

    app = create_app(Factory())
    response = TestClient(app).post(
        "/scan/universe/nifty500?run_id=immutable-run",
        json={"limit": 25},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["message"] == "scan run_id already exists"
    assert detail["run_id"] == "immutable-run"
    assert detail["existing_outcome"] == "completed"
    assert audit.get("immutable-run") == original
    assert app.state.scan_execution_guard.status()["status"] == "idle"


def test_duplicate_active_run_id_does_not_steal_primary_audit_identity():
    audit = FakeAuditService()

    class Factory:
        def scan_run_audit_service(self):
            return audit

    app = create_app(Factory())
    guard = app.state.scan_execution_guard
    assert guard.try_start("active-run") is True

    response = TestClient(app).post(
        "/scan/universe/nifty500?run_id=active-run",
        json={"limit": 25},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["duplicate_active_run_id"] is True
    assert audit.get("active-run") is None

    guard.finish("active-run", "completed")


def test_nifty500_time_budgets_are_propagated_to_scanner():
    universe = FakeNifty500Universe()
    scanner = FakeUniverseScanner()

    class Factory:
        def nifty500_universe(self):
            return universe

        def scanner_service(self):
            return scanner

    response = TestClient(create_app(Factory())).post(
        "/scan/universe/nifty500",
        json={
            "limit": 25,
            "batch_size": 25,
            "batch_pause_seconds": 0,
            "scan_time_budget_seconds": 300,
            "batch_time_budget_seconds": 45,
        },
    )

    assert response.status_code == 200
    _, kwargs = scanner.calls[0]
    assert kwargs["scan_time_budget_seconds"] == 300
    assert kwargs["batch_time_budget_seconds"] == 45


def test_nifty500_partial_time_budget_run_is_audited_and_releases_guard():
    universe = FakeNifty500Universe()
    audit = FakeAuditService()

    class PartialScanner:
        def scan_universe(self, symbols, **kwargs):
            processed = symbols[:25]
            deferred = symbols[25:]
            return {
                "outcome": "partial",
                "results": [],
                "rejected": [
                    {
                        "symbol": symbol,
                        "signal": "HOLD",
                        "passed": False,
                    }
                    for symbol in processed
                ] + [
                    {
                        "symbol": symbol,
                        "signal": "ERROR",
                        "passed": False,
                        "error": (
                            "time_budget_deferred:"
                            "scan_time_budget_exhausted_after_batch"
                        ),
                    }
                    for symbol in deferred
                ],
                "scanned_count": len(symbols),
                "count": 0,
                "rejected_count": len(symbols),
                "top_picks": [],
                "scale_gate": {
                    "requested_symbols": len(symbols),
                    "unique_symbols": len(symbols),
                    "accounted_symbols": len(symbols),
                    "completed_symbols": len(processed),
                    "error_symbols": len(deferred),
                    "missing_symbols": 0,
                    "processed_symbols": len(processed),
                    "processed_pct": 50.0,
                    "deferred_symbols": deferred,
                    "deferred_symbol_count": len(deferred),
                    "graceful_degradation": True,
                    "time_budget_exhausted": True,
                    "time_budget_stop_reason": (
                        "scan_time_budget_exhausted_after_batch"
                    ),
                    "time_budget_stop_batch": 1,
                    "scan_time_budget_seconds": kwargs[
                        "scan_time_budget_seconds"
                    ],
                    "batch_time_budget_seconds": kwargs[
                        "batch_time_budget_seconds"
                    ],
                    "duration_sec": 20.0,
                    "errors": deferred,
                    "error_details": {
                        symbol: "time_budget_deferred"
                        for symbol in deferred
                    },
                    "enrichment_failure_symbols": [],
                    "enrichment_failures": 0,
                    "enrichment_failure_events": 0,
                    "enrichment_failure_fields": {},
                    "enrichment_failure_details": {},
                    "execution_error_symbols": [],
                    "execution_errors": 0,
                    "missing": [],
                    "batches": [],
                },
            }

    class Factory:
        def nifty500_universe(self):
            return universe

        def scanner_service(self):
            return PartialScanner()

        def scan_run_audit_service(self):
            return audit

    app = create_app(Factory())
    response = TestClient(app).post(
        "/scan/universe/nifty500?run_id=partial-budget-run",
        json={
            "limit": 50,
            "batch_size": 25,
            "batch_pause_seconds": 0,
            "scan_time_budget_seconds": 300,
            "batch_time_budget_seconds": 45,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "partial"
    assert body["scale_gate"]["outcome"] == "partial"
    assert body["scale_gate"]["time_budget_exhausted"] is True
    assert body["scale_gate"]["processed_symbols"] == 25
    assert body["scale_gate"]["deferred_symbol_count"] == 25

    record = audit.get("partial-budget-run")
    assert record["outcome"] == "partial"
    assert record["http_status"] == 200
    assert record["failure_stage"] == "time_budget"
    assert record["failure_message"] == (
        "scan_time_budget_exhausted_after_batch"
    )
    assert record["completed_symbols"] == 25
    assert record["error_symbols"] == 25
    assert record["metadata"]["time_budget_exhausted"] is True
    assert record["metadata"]["processed_symbols"] == 25
    assert record["metadata"]["deferred_symbol_count"] == 25

    runtime = app.state.scan_execution_guard.status()
    assert runtime["status"] == "idle"
    assert runtime["last_completed"]["run_id"] == "partial-budget-run"
    assert runtime["last_completed"]["outcome"] == "partial"
