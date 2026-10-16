from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class Member:
    symbol = "TCS"
    name = "TCS"
    series = "EQ"


class Universe:
    def ensure_loaded(self, refresh=False):
        return [Member()]

    def report(self, include_members=False):
        return {
            "status": "healthy",
            "index": "NIFTY 500",
            "nominal_company_count": 500,
            "count": 1,
            "security_count": 1,
            "source": "NSE_NIFTY500_CSV",
        }


class Scanner:
    def __init__(self, fail=False):
        self.fail = fail

    def scan_universe(self, symbols, **kwargs):
        if self.fail:
            raise ValueError("bad scanner input")
        pick = {
            "symbol": "TCS",
            "signal": {
                "signal": "BUY",
                "overall_score": 94.0,
                "confidence": 81.0,
            },
            "eligible": True,
            "execution_eligible": True,
            "ranking_score": 94.0,
        }
        return {
            "results": [pick],
            "eligible": [pick],
            "rejected": [],
            "top_picks": [pick],
            "execution_top_picks": [pick],
            "analysis_top_picks": [pick],
            "analysis_count": 1,
            "execution_count": 1,
            "count": 1,
            "rejected_count": 0,
            "scanned_count": 1,
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


class Producer:
    def __init__(self):
        self.completed = []
        self.failed = []

    def scan_completed(
        self,
        result,
        *,
        run_id,
        continuation=False,
    ):
        self.completed.append(
            {
                "run_id": run_id,
                "continuation": continuation,
                "has_execution_picks": bool(
                    result.get("execution_top_picks")
                ),
                "outcome": result.get("outcome"),
            }
        )
        return {
            "status": "processed",
            "pick_event_count": 1,
        }

    def scan_failed(self, **kwargs):
        self.failed.append(dict(kwargs))
        return {"status": "sent"}

    def health(self):
        return {
            "status": "ready",
            "best_effort": True,
            "attempted": (
                len(self.completed) + len(self.failed)
            ),
            "failures": 0,
        }


class Factory:
    def __init__(self, *, fail=False):
        self.universe = Universe()
        self.scanner = Scanner(fail=fail)
        self.producer = Producer()

    def nifty500_universe(self):
        return self.universe

    def scanner_service(self):
        return self.scanner

    def notification_producer_service(self):
        return self.producer


def test_notification_producer_health_endpoint():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.get("/notifications/producers")

    assert response.status_code == 200
    assert response.json()["best_effort"] is True
    assert response.json()["attempted"] == 0


def test_completed_scan_dispatches_before_compact_projection():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post(
        "/scan/universe/nifty500?run_id=notify-scan",
        json={
            "limit": 1,
            "batch_size": 1,
            "batch_pause_seconds": 0,
            "compact": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["notification_dispatch"] == {
        "status": "processed",
        "pick_event_count": 1,
    }
    assert len(factory.producer.completed) == 1
    call = factory.producer.completed[0]
    assert call["run_id"] == "notify-scan"
    assert call["outcome"] == "completed"
    assert call["has_execution_picks"] is True
    assert call["continuation"] is False


def test_scan_value_error_emits_failure_without_changing_http_status():
    factory = Factory(fail=True)
    client = TestClient(create_app(factory))

    response = client.post(
        "/scan/universe/nifty500?run_id=notify-failure",
        json={
            "limit": 1,
            "batch_size": 1,
            "batch_pause_seconds": 0,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "bad scanner input"
    assert len(factory.producer.failed) == 1
    failure = factory.producer.failed[0]
    assert failure["run_id"] == "notify-failure"
    assert failure["failure_stage"] == "scan_execution"
    assert failure["http_status"] == 422
