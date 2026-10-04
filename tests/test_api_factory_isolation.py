"""Injected FastAPI application instances must not share mutable factory state."""
from fastapi.testclient import TestClient
from api.app import create_app


class Factory:
    def __init__(self, label):
        self.label = label

    def health(self):
        return {"status": "configured", "factory": self.label}

    def scanner_service(self):
        label = self.label

        class Scanner:
            def scan(self, symbol, **kwargs):
                return {"symbol": symbol, "factory": label}

            def scan_many(self, symbols, **kwargs):
                return {"symbols": symbols, "factory": label}

        return Scanner()


def test_injected_app_factories_remain_isolated():
    first = create_app(Factory("first"), database_initializer=lambda: {"status": "initialized"})
    second = create_app(Factory("second"), database_initializer=lambda: {"status": "initialized"})
    with TestClient(first) as a, TestClient(second) as b:
        assert a.get("/health").json()["factory"] == "first"
        assert b.get("/health").json()["factory"] == "second"
        assert a.get("/scan/abc").json()["factory"] == "first"
        assert b.post("/scan", json={"symbols": ["ABC"]}).json()["factory"] == "second"
