from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from database.repositories.scan_run_audit_repository import (
    DuplicateScanRunIdError,
)
from database.repositories.scan_continuation_repository import (
    ContinuationNotFoundError,
    ContinuationUnavailableError,
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


class FakeContinuationService:
    def __init__(self):
        self.records = {}
        self.counter = 0

    def create(
        self,
        *,
        parent_run_id,
        symbols,
        request,
        lineage_root_run_id=None,
        generation=1,
    ):
        self.counter += 1
        token = f"token-{self.counter}"
        if any(
            record["parent_run_id"] == parent_run_id
            for record in self.records.values()
        ):
            raise ValueError(
                f"continuation already exists for parent run {parent_run_id}"
            )
        record = {
            "id": self.counter,
            "token": token,
            "parent_run_id": parent_run_id,
            "lineage_root_run_id": (
                lineage_root_run_id or parent_run_id
            ),
            "generation": generation,
            "status": "pending",
            "symbols": list(symbols),
            "request": dict(request),
            "child_run_id": None,
            "created_at": "2026-10-14T04:00:00+00:00",
            "claimed_at": None,
            "consumed_at": None,
            "updated_at": "2026-10-14T04:00:00+00:00",
        }
        self.records[token] = record
        return dict(record)

    def inspect(self, token):
        record = self.records.get(str(token))
        if record is None:
            raise ContinuationNotFoundError(
                "scan continuation token not found"
            )
        return dict(record)

    def claim(self, token, child_run_id):
        record = self.records.get(str(token))
        if record is None:
            raise ContinuationNotFoundError(
                "scan continuation token not found"
            )
        if record["status"] != "pending":
            raise ContinuationUnavailableError(
                "scan continuation token is not pending"
            )
        record["status"] = "active"
        record["child_run_id"] = child_run_id
        record["claimed_at"] = "2026-10-14T04:01:00+00:00"
        return dict(record)

    def consume(self, token, child_run_id):
        record = self.records.get(str(token))
        if (
            record is None
            or record["status"] != "active"
            or record["child_run_id"] != child_run_id
        ):
            raise ContinuationUnavailableError(
                "scan continuation token could not be consumed"
            )
        record["status"] = "consumed"
        record["consumed_at"] = "2026-10-14T04:02:00+00:00"
        return dict(record)

    def restore_pending(self, token, child_run_id):
        record = self.records.get(str(token))
        if (
            record is not None
            and record.get("child_run_id") == child_run_id
            and record.get("status") in {"active", "consumed"}
        ):
            record["status"] = "pending"
            record["child_run_id"] = None
            record["claimed_at"] = None
            record["consumed_at"] = None
        return dict(record) if record is not None else None

    def delete_pending(self, token, parent_run_id):
        record = self.records.get(str(token))
        if (
            record is not None
            and record["parent_run_id"] == parent_run_id
            and record["status"] == "pending"
            and record["child_run_id"] is None
        ):
            del self.records[str(token)]

    def health(self):
        statuses = {"pending": 0, "active": 0, "consumed": 0}
        for record in self.records.values():
            statuses[record["status"]] += 1
        return {
            "status": "ready",
            **statuses,
            "records": len(self.records),
        }


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
                            "batch_time_budget_exceeded"
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
                    "progress_semantics_version": "R66.7",
                    "accounted_pct": 100.0,
                    "processed_pct": 50.0,
                    "successful_pct": 50.0,
                    "error_pct": 50.0,
                    "deferred_pct": 50.0,
                    "missing_pct": 0.0,
                    "completion_pct": 100.0,
                    "completion_pct_semantics": (
                        "legacy_alias_of_accounted_pct"
                    ),
                    "deferred_symbols": deferred,
                    "deferred_symbol_count": len(deferred),
                    "graceful_degradation": True,
                    "time_budget_exhausted": True,
                    "time_budget_stop_reason": (
                        "batch_time_budget_exceeded"
                    ),
                    "time_budget_stop_batch": 1,
                    "scan_time_budget_seconds": kwargs[
                        "scan_time_budget_seconds"
                    ],
                    "batch_time_budget_seconds": kwargs[
                        "batch_time_budget_seconds"
                    ],
                    "duration_sec": 50.0,
                    "scan_budget_headroom_sec": 250.0,
                    "scan_budget_utilization_pct": 16.67,
                    "scan_sla_met": True,
                    "batch_sla_met": False,
                    "sla_met": False,
                    "sla_status": "breached",
                    "max_batch_duration_sec": 50.0,
                    "avg_batch_duration_sec": 50.0,
                    "batch_budget_breach_count": 1,
                    "peak_batch_budget_utilization_pct": 111.11,
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
        "batch_time_budget_exceeded"
    )
    assert record["completed_symbols"] == 25
    assert record["error_symbols"] == 25
    assert record["metadata"]["time_budget_exhausted"] is True
    assert record["metadata"]["processed_symbols"] == 25
    assert record["metadata"]["deferred_symbol_count"] == 25
    assert record["metadata"]["progress_semantics_version"] == "R66.7"
    assert record["metadata"]["accounted_pct"] == 100.0
    assert record["metadata"]["processed_pct"] == 50.0
    assert record["metadata"]["successful_pct"] == 50.0
    assert record["metadata"]["completion_pct_semantics"] == (
        "legacy_alias_of_accounted_pct"
    )
    assert record["metadata"]["sla_status"] == "breached"
    assert record["metadata"]["sla_met"] is False
    assert record["metadata"]["batch_budget_breach_count"] == 1

    runtime = app.state.scan_execution_guard.status()
    assert runtime["status"] == "idle"
    assert runtime["last_completed"]["run_id"] == "partial-budget-run"
    assert runtime["last_completed"]["outcome"] == "partial"



class ContinuationFlowScanner:
    def __init__(self, fail_child_once=False, child_partial=False):
        self.calls = []
        self.fail_child_once = fail_child_once
        self.child_partial = child_partial
        self._child_failed = False

    @staticmethod
    def _result(symbols, *, partial=False):
        symbols = list(symbols)
        if partial:
            processed = symbols[: max(1, len(symbols) // 2)]
            deferred = symbols[len(processed):]
        else:
            processed = symbols
            deferred = []

        rejected = [
            {
                "symbol": symbol,
                "signal": "HOLD",
                "eligible": False,
            }
            for symbol in processed
        ]
        rejected.extend(
            {
                "symbol": symbol,
                "signal": "ERROR",
                "eligible": False,
                "error": (
                    "time_budget_deferred:"
                    "batch_time_budget_exceeded"
                ),
            }
            for symbol in deferred
        )

        total = len(symbols)
        processed_count = len(processed)
        deferred_count = len(deferred)
        processed_pct = round(
            processed_count / total * 100.0 if total else 100.0,
            2,
        )
        deferred_pct = round(
            deferred_count / total * 100.0 if total else 0.0,
            2,
        )

        return {
            "outcome": "partial" if partial else "completed",
            "results": [],
            "rejected": rejected,
            "scanned_count": total,
            "count": 0,
            "rejected_count": total,
            "top_picks": [],
            "scale_gate": {
                "requested_symbols": total,
                "unique_symbols": total,
                "accounted_symbols": total,
                "completed_symbols": processed_count,
                "error_symbols": deferred_count,
                "missing_symbols": 0,
                "progress_semantics_version": "R66.7",
                "accounted_pct": 100.0,
                "processed_pct": processed_pct,
                "successful_pct": processed_pct,
                "error_pct": deferred_pct,
                "deferred_pct": deferred_pct,
                "missing_pct": 0.0,
                "completion_pct": 100.0,
                "completion_pct_semantics": (
                    "legacy_alias_of_accounted_pct"
                ),
                "processed_symbols": processed_count,
                "deferred_symbols": deferred,
                "deferred_symbol_count": deferred_count,
                "graceful_degradation": partial,
                "time_budget_exhausted": partial,
                "time_budget_stop_reason": (
                    "batch_time_budget_exceeded"
                    if partial
                    else None
                ),
                "time_budget_stop_batch": 1 if partial else None,
                "scan_time_budget_seconds": 120.0,
                "batch_time_budget_seconds": 5.0 if partial else 60.0,
                "budget_remaining_sec": 100.0,
                "scan_budget_headroom_sec": 100.0,
                "scan_budget_utilization_pct": 16.67,
                "scan_sla_met": True,
                "batch_sla_met": not partial,
                "sla_met": not partial,
                "sla_status": "breached" if partial else "met",
                "max_batch_duration_sec": 20.0,
                "avg_batch_duration_sec": 20.0,
                "batch_budget_breach_count": 1 if partial else 0,
                "peak_batch_budget_utilization_pct": (
                    400.0 if partial else 33.33
                ),
                "duration_sec": 20.0,
                "errors": deferred,
                "error_details": {
                    symbol: (
                        "time_budget_deferred:"
                        "batch_time_budget_exceeded"
                    )
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

    def scan_universe(self, symbols, **kwargs):
        call_number = len(self.calls) + 1
        self.calls.append((list(symbols), dict(kwargs)))

        if call_number == 1:
            return self._result(symbols, partial=True)

        if self.fail_child_once and not self._child_failed:
            self._child_failed = True
            raise RuntimeError("simulated continuation child failure")

        return self._result(
            symbols,
            partial=self.child_partial,
        )


def test_partial_scan_creates_one_time_continuation_and_child_resumes_only_deferred_symbols():
    universe = FakeNifty500Universe()
    scanner = ContinuationFlowScanner()
    audit = FakeAuditService()
    continuations = FakeContinuationService()

    class Factory:
        def nifty500_universe(self):
            return universe

        def scanner_service(self):
            return scanner

        def scan_run_audit_service(self):
            return audit

        def scan_continuation_service(self):
            return continuations

    app = create_app(Factory())
    client = TestClient(app)

    parent = client.post(
        "/scan/universe/nifty500?run_id=parent-run",
        json={
            "period": "1y",
            "interval": "1d",
            "capital": 12345,
            "top_n": 7,
            "limit": 50,
            "batch_size": 20,
            "batch_pause_seconds": 0.25,
            "scan_time_budget_seconds": 120,
            "batch_time_budget_seconds": 5,
        },
    )

    assert parent.status_code == 200
    parent_body = parent.json()
    assert parent_body["outcome"] == "partial"
    continuation = parent_body["continuation"]
    assert continuation["status"] == "pending"
    assert continuation["parent_run_id"] == "parent-run"
    assert continuation["lineage_root_run_id"] == "parent-run"
    assert continuation["generation"] == 1
    assert continuation["symbol_count"] == 25
    token = continuation["token"]

    parent_record = audit.get("parent-run")
    assert parent_record["metadata"]["deferred_symbol_count"] == 25
    assert parent_record["metadata"]["deferred_symbols"] == [
        f"SYM{i}" for i in range(25, 50)
    ]
    assert parent_record["metadata"]["is_continuation"] is False
    assert parent_record["metadata"]["lineage_root_run_id"] == "parent-run"
    assert parent_record["metadata"]["continuation_generation"] == 0
    assert parent_record["metadata"]["next_continuation_available"] is True
    assert "continuation_token" not in parent_record["metadata"]

    child = client.post(
        (
            "/scan/universe/nifty500"
            f"?run_id=child-run&continuation_token={token}"
        ),
        json={
            "batch_time_budget_seconds": 90,
        },
    )

    assert child.status_code == 200
    child_body = child.json()
    assert child_body["outcome"] == "completed"
    assert child_body["resumed_from"] == {
        "parent_run_id": "parent-run",
        "lineage_root_run_id": "parent-run",
        "generation": 1,
        "symbol_count": 25,
    }

    assert len(scanner.calls) == 2
    child_symbols, child_kwargs = scanner.calls[1]
    assert child_symbols == [f"SYM{i}" for i in range(25, 50)]
    assert child_kwargs["period"] == "1y"
    assert child_kwargs["interval"] == "1d"
    assert child_kwargs["capital"] == 12345
    assert child_kwargs["top_n"] == 7
    assert child_kwargs["batch_size"] == 20
    assert child_kwargs["batch_pause_seconds"] == 0.25
    assert child_kwargs["scan_time_budget_seconds"] == 120
    assert child_kwargs["batch_time_budget_seconds"] == 90

    token_record = continuations.inspect(token)
    assert token_record["status"] == "consumed"
    assert token_record["child_run_id"] == "child-run"

    child_record = audit.get("child-run")
    assert child_record["outcome"] == "completed"
    assert child_record["metadata"]["is_continuation"] is True
    assert child_record["metadata"]["parent_run_id"] == "parent-run"
    assert child_record["metadata"]["lineage_root_run_id"] == "parent-run"
    assert child_record["metadata"]["continuation_generation"] == 1
    assert child_record["metadata"]["next_continuation_available"] is False

    lineage = client.get(
        f"/observability/scan-continuations/{token}"
    )
    assert lineage.status_code == 200
    lineage_body = lineage.json()
    assert "token" not in lineage_body
    assert lineage_body["status"] == "consumed"
    assert lineage_body["parent_run_id"] == "parent-run"
    assert lineage_body["child_run_id"] == "child-run"
    assert lineage_body["parent_audit"]["run_id"] == "parent-run"
    assert lineage_body["child_audit"]["run_id"] == "child-run"

    replay = client.post(
        (
            "/scan/universe/nifty500"
            f"?run_id=replay-run&continuation_token={token}"
        ),
        json={},
    )
    assert replay.status_code == 409
    assert len(scanner.calls) == 2
    replay_audit = audit.get("replay-run")
    assert replay_audit["outcome"] == "rejected"
    assert replay_audit["failure_stage"] == "continuation_validation"
    assert replay_audit["metadata"]["continuation_status"] == "consumed"
    assert replay_audit["metadata"]["existing_child_run_id"] == "child-run"


def test_failed_continuation_child_releases_token_for_retry_under_new_run_id():
    universe = FakeNifty500Universe()
    scanner = ContinuationFlowScanner(fail_child_once=True)
    audit = FakeAuditService()
    continuations = FakeContinuationService()

    class Factory:
        def nifty500_universe(self):
            return universe

        def scanner_service(self):
            return scanner

        def scan_run_audit_service(self):
            return audit

        def scan_continuation_service(self):
            return continuations

    client = TestClient(create_app(Factory()))

    parent = client.post(
        "/scan/universe/nifty500?run_id=retry-parent",
        json={
            "limit": 50,
            "batch_time_budget_seconds": 5,
        },
    )
    token = parent.json()["continuation"]["token"]

    failed = client.post(
        (
            "/scan/universe/nifty500"
            f"?run_id=failed-child&continuation_token={token}"
        ),
        json={},
    )
    assert failed.status_code == 503
    assert audit.get("failed-child")["outcome"] == "failed"
    assert continuations.inspect(token)["status"] == "pending"
    assert continuations.inspect(token)["child_run_id"] is None

    retry = client.post(
        (
            "/scan/universe/nifty500"
            f"?run_id=retry-child&continuation_token={token}"
        ),
        json={},
    )
    assert retry.status_code == 200
    assert retry.json()["outcome"] == "completed"
    assert continuations.inspect(token)["status"] == "consumed"
    assert continuations.inspect(token)["child_run_id"] == "retry-child"


def test_partial_continuation_child_creates_next_generation_token():
    universe = FakeNifty500Universe()
    scanner = ContinuationFlowScanner(child_partial=True)
    audit = FakeAuditService()
    continuations = FakeContinuationService()

    class Factory:
        def nifty500_universe(self):
            return universe

        def scanner_service(self):
            return scanner

        def scan_run_audit_service(self):
            return audit

        def scan_continuation_service(self):
            return continuations

    client = TestClient(create_app(Factory()))

    parent = client.post(
        "/scan/universe/nifty500?run_id=chain-parent",
        json={
            "limit": 50,
            "batch_time_budget_seconds": 5,
        },
    )
    first = parent.json()["continuation"]
    first_token = first["token"]

    child = client.post(
        (
            "/scan/universe/nifty500"
            f"?run_id=chain-child&continuation_token={first_token}"
        ),
        json={
            "batch_time_budget_seconds": 5,
        },
    )

    assert child.status_code == 200
    child_body = child.json()
    assert child_body["outcome"] == "partial"
    second = child_body["continuation"]
    assert second["parent_run_id"] == "chain-child"
    assert second["lineage_root_run_id"] == "chain-parent"
    assert second["generation"] == 2
    assert second["symbol_count"] < first["symbol_count"]

    assert continuations.inspect(first_token)["status"] == "consumed"
    second_record = continuations.inspect(second["token"])
    assert second_record["status"] == "pending"
    assert second_record["generation"] == 2

    child_audit = audit.get("chain-child")
    assert child_audit["metadata"]["parent_run_id"] == "chain-parent"
    assert child_audit["metadata"]["continuation_generation"] == 1
    assert child_audit["metadata"]["next_continuation_available"] is True
