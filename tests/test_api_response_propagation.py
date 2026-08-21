from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app


class StubScanner:
    def scan(self, symbol, **kwargs):
        return {
            "symbol": symbol.upper(),
            "score": 87.5,
            "confidence": 91.0,
            "signal": "BUY",
            "eligible": True,
            "rejection_reason": None,
            "rejection_reasons": [],
            "execution_errors": [],
        }

    def scan_many(self, symbols, **kwargs):
        good = {
            "symbol": "GOOD",
            "score": 90.0,
            "confidence": 95.0,
            "signal": "BUY",
            "eligible": True,
            "rejection_reason": None,
            "rejection_reasons": [],
            "execution_errors": [],
        }
        bad = {
            "symbol": "BAD",
            "score": 99.0,
            "confidence": 99.0,
            "signal": "SELL",
            "eligible": False,
            "rejection_reason": "negative_signal:sell",
            "rejection_reasons": ["negative_signal:sell"],
            "execution_errors": ["Risk Engine: blocked"],
        }
        return {
            "results": [good],
            "eligible": [good],
            "rejected": [bad],
            "top_picks": [good],
            "count": 1,
            "rejected_count": 1,
            "scanned_count": 2,
        }


class StubFactory:
    def scanner_service(self):
        return StubScanner()

    def health(self):
        return {"status": "healthy"}


def test_single_scan_preserves_decision_fields(monkeypatch):
    monkeypatch.setattr("api.app.get_application", lambda: StubFactory())
    response = TestClient(app).get("/scan/abc")
    assert response.status_code == 200
    body = response.json()
    assert body["score"] == 87.5
    assert body["confidence"] == 91.0
    assert body["signal"] == "BUY"
    assert body["eligible"] is True
    assert body["rejection_reason"] is None
    assert body["rejection_reasons"] == []


def test_batch_scan_preserves_rejections_and_top_picks(monkeypatch):
    monkeypatch.setattr("api.app.get_application", lambda: StubFactory())
    response = TestClient(app).post("/scan", json={"symbols": ["GOOD", "BAD"]})
    assert response.status_code == 200
    body = response.json()
    assert body["top_picks"][0]["symbol"] == "GOOD"
    assert body["rejected"][0]["rejection_reason"] == "negative_signal:sell"
    assert body["rejected"][0]["rejection_reasons"] == ["negative_signal:sell"]
    assert body["rejected"][0]["execution_errors"] == ["Risk Engine: blocked"]
    assert body["rejected_count"] == 1
    assert body["scanned_count"] == 2
