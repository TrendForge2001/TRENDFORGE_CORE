from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from api.production_runtime import secure_application


class Member:
    def __init__(self, symbol):
        self.symbol = symbol
        self.name = symbol
        self.series = "EQ"


class Universe:
    def __init__(self):
        self.members = [Member("TCS")]

    def ensure_loaded(self, refresh=False):
        return list(self.members)

    def report(self, include_members=False):
        return {
            "status": "healthy",
            "index": "NIFTY 500",
            "nominal_company_count": 500,
            "count": 1,
            "security_count": 1,
            "source": "TEST",
        }


class Scanner:
    def scan_universe(self, symbols, **kwargs):
        assert symbols == ["TCS"]
        pick = {
            "symbol": "TCS",
            "signal": {
                "signal": "BUY",
                "overall_score": 92.0,
                "confidence": 80.0,
                "entry": 3000.0,
                "stoploss": 2950.0,
                "target2": 3100.0,
            },
            "eligible": True,
            "ranking_score": 92.0,
            "passed": True,
            "confidence": 80.0,
            "engines": {},
        }
        return {
            "results": [pick],
            "eligible": [pick],
            "rejected": [],
            "top_picks": [pick],
            "scanned_count": 1,
            "count": 1,
            "rejected_count": 0,
            "scale_gate": {
                "requested_symbols": 1,
                "unique_symbols": 1,
                "accounted_symbols": 1,
                "completed_symbols": 1,
                "error_symbols": 0,
                "missing_symbols": 0,
                "time_budget_exhausted": False,
                "deferred_symbols": [],
                "deferred_symbol_count": 0,
            },
        }


class AutoEntry:
    def __init__(self):
        self.calls = []

    def process_scan(
        self,
        scan_result,
        *,
        run_id,
        execute_requested,
        continuation=False,
        now=None,
    ):
        self.calls.append(
            {
                "run_id": run_id,
                "execute_requested": execute_requested,
                "continuation": continuation,
                "top_picks": list(
                    scan_result.get("top_picks") or []
                ),
                "outcome": scan_result.get("outcome"),
            }
        )
        return {
            "status": "executed",
            "run_id": run_id,
            "opened_count": 1,
            "opened": [{"symbol": "TCS", "trade_id": 7}],
            "evaluations": [],
            "broker_orders_allowed": False,
        }

    def health(self):
        return {
            "status": "ready",
            "enabled": True,
            "paper_only": True,
            "broker_orders_allowed": False,
        }


class Factory:
    def __init__(self):
        self.universe = Universe()
        self.scanner = Scanner()
        self.auto = AutoEntry()

    def nifty500_universe(self):
        return self.universe

    def scanner_service(self):
        return self.scanner

    def paper_auto_entry_service(self):
        return self.auto


def test_universe_scan_requires_explicit_request_opt_in_for_auto_entry():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post(
        "/scan/universe/nifty500?run_id=no-entry",
        json={
            "limit": 1,
            "batch_size": 1,
            "batch_pause_seconds": 0,
            "paper_auto_entry": False,
        },
    )

    assert response.status_code == 200
    assert factory.auto.calls == []
    assert "paper_auto_entry" not in response.json()


def test_universe_scan_hands_rich_completed_result_to_auto_entry():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post(
        "/scan/universe/nifty500?run_id=entry-run",
        json={
            "limit": 1,
            "batch_size": 1,
            "batch_pause_seconds": 0,
            "paper_auto_entry": True,
            "compact": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["paper_auto_entry"]["status"] == "executed"
    assert body["paper_auto_entry"]["broker_orders_allowed"] is False

    assert len(factory.auto.calls) == 1
    call = factory.auto.calls[0]
    assert call["run_id"] == "entry-run"
    assert call["execute_requested"] is True
    assert call["continuation"] is False
    assert call["outcome"] == "completed"
    assert call["top_picks"][0]["symbol"] == "TCS"


def test_auto_entry_readiness_endpoint_uses_canonical_service():
    factory = Factory()
    response = TestClient(create_app(factory)).get(
        "/paper/auto-entry/readiness"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["broker_orders_allowed"] is False


def test_production_universe_scan_requires_admin_key(monkeypatch):
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY",
        "a" * 40,
    )
    app = secure_application(create_app(Factory()))
    client = TestClient(app)

    denied = client.post(
        "/scan/universe/nifty500?run_id=protected",
        json={
            "limit": 1,
            "batch_size": 1,
            "batch_pause_seconds": 0,
        },
    )

    assert denied.status_code == 401

    allowed = client.post(
        "/scan/universe/nifty500?run_id=protected-ok",
        json={
            "limit": 1,
            "batch_size": 1,
            "batch_pause_seconds": 0,
        },
        headers={
            "X-TrendForge-Admin-Key": "a" * 40,
        },
    )

    assert allowed.status_code == 200
