"""Scan API rejects invalid capital before reaching the scanner."""
from fastapi.testclient import TestClient
from api.app import create_app


class Factory:
    def scanner_service(self):
        raise AssertionError("Invalid requests must not invoke the scanner")


def test_batch_rejects_negative_capital():
    app = create_app(Factory())
    response = TestClient(app).post("/scan", json={"symbols": ["ABC"], "capital": -1})
    assert response.status_code == 422


def test_batch_rejects_nonfinite_capital():
    app = create_app(Factory())
    response = TestClient(app).post("/scan", json={"symbols": ["ABC"], "capital": "Infinity"})
    assert response.status_code == 422


def test_single_rejects_negative_capital():
    app = create_app(Factory())
    response = TestClient(app).get("/scan/ABC?capital=-1")
    assert response.status_code == 422
