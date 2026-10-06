from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from api.app import app


def test_root_contract():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "TrendForge Core"


def test_health_uses_application_factory(monkeypatch):
    class Application:
        def health(self):
            return {"status": "healthy"}

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_single_scan_uses_scanner_service(monkeypatch):
    calls = []

    class ScannerService:
        def scan(self, symbol, **kwargs):
            calls.append(("single", symbol, kwargs))
            return {"symbol": symbol.upper(), "eligible": True}

    monkeypatch.setattr("api.app.get_scanner_service", lambda: ScannerService())
    response = TestClient(app).get("/scan/abc")
    assert response.status_code == 200
    assert response.json()["symbol"] == "ABC"
    assert calls[0][0] == "single"


def test_batch_scan_uses_scanner_service(monkeypatch):
    calls = []

    class ScannerService:
        def scan_many(self, symbols, **kwargs):
            calls.append((symbols, kwargs))
            return {"scanned_count": len(symbols), "top_picks": []}

    monkeypatch.setattr("api.app.get_scanner_service", lambda: ScannerService())
    response = TestClient(app).post("/scan", json={"symbols": ["AAA", "BBB"]})
    assert response.status_code == 200
    assert response.json()["scanned_count"] == 2
    assert calls[0][0] == ["AAA", "BBB"]



def test_fundamental_template_download_uses_manager(monkeypatch):
    class Manager:
        def template_csv(self):
            return b"Symbol,ROCE,ROE\n"

    class Application:
        def fundamental_manager(self):
            return Manager()

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).get("/fundamentals/template.csv")

    assert response.status_code == 200
    assert response.content == b"Symbol,ROCE,ROE\n"
    assert "trendforge_fundamentals_template.csv" in response.headers["content-disposition"]


def test_fundamental_report_uses_manager(monkeypatch):
    calls = []

    class Manager:
        def report(self, **kwargs):
            calls.append(kwargs)
            return {"total_records": 2, "records": []}

    class Application:
        def fundamental_manager(self):
            return Manager()

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).get(
        "/fundamentals?limit=50&incomplete_only=true&stale_only=false"
    )

    assert response.status_code == 200
    assert response.json()["total_records"] == 2
    assert calls == [
        {"limit": 50, "incomplete_only": True, "stale_only": False}
    ]


def test_fundamental_symbol_lookup_and_manual_update(monkeypatch):
    calls = []

    class Manager:
        def inspect(self, symbol):
            return {
                "symbol": symbol.upper(),
                "fundamentals": {"roce": 20.0},
                "quality": {"ready": False},
            }

        def upsert(self, symbol, values, *, source, as_of):
            calls.append((symbol, values, source, as_of))
            return {
                "symbol": symbol.upper(),
                "fundamentals": values,
                "quality": {"ready": False},
            }

    manager = Manager()

    class Application:
        def fundamental_manager(self):
            return manager

    monkeypatch.setattr("api.app.get_application", lambda: Application())

    lookup = TestClient(app).get("/fundamentals/abc")
    assert lookup.status_code == 200
    assert lookup.json()["symbol"] == "ABC"

    update = TestClient(app).put(
        "/fundamentals/nse:abc",
        json={
            "roce": 25.0,
            "roe": 18.0,
            "source": "manual_research",
            "as_of": "2026-10-06T00:00:00+00:00",
        },
    )
    assert update.status_code == 200
    assert calls[0][0] == "nse:abc"
    assert calls[0][1] == {"roce": 25.0, "roe": 18.0}
    assert calls[0][2] == "manual_research"


def test_fundamental_upload_preserves_original_filename(monkeypatch):
    calls = []

    class Manager:
        def import_file(self, path, **kwargs):
            from pathlib import Path

            path = Path(path)
            calls.append((path.exists(), path.suffix, kwargs))
            return {
                "status": "imported",
                "imported": 1,
                "source_file": kwargs["source_file_name"],
            }

    class Application:
        def fundamental_manager(self):
            return Manager()

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).post(
        "/fundamentals/upload",
        files={
            "file": (
                "My Fundamentals.csv",
                b"Symbol,ROCE\nABC,20\n",
                "text/csv",
            )
        },
        data={"source": "manual_upload"},
    )

    assert response.status_code == 200
    assert response.json()["source_file"] == "My Fundamentals.csv"
    assert calls[0][0] is True
    assert calls[0][1] == ".csv"
    assert calls[0][2]["source_file_name"] == "My Fundamentals.csv"


def test_fundamental_manual_update_rejects_invalid_ranges(monkeypatch):
    class Manager:
        def upsert(self, *args, **kwargs):
            raise AssertionError("Pydantic validation should reject first")

    class Application:
        def fundamental_manager(self):
            return Manager()

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).put(
        "/fundamentals/ABC",
        json={"promoter_holding": 125.0},
    )

    assert response.status_code == 422



def test_fundamental_completion_download_uses_completion_service(monkeypatch):
    class CompletionService:
        def completion_xlsx(self):
            return b"completion-xlsx"

    class Application:
        def fundamental_completion_service(self):
            return CompletionService()

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).get("/fundamentals/completion.xlsx")

    assert response.status_code == 200
    assert response.content == b"completion-xlsx"
    assert (
        "trendforge_fundamental_completion.xlsx"
        in response.headers["content-disposition"]
    )


def test_fundamental_completion_upload_defaults_to_preview(monkeypatch):
    calls = []

    class CompletionService:
        def process_file(self, path, **kwargs):
            from pathlib import Path

            path = Path(path)
            calls.append((path.exists(), path.suffix, kwargs))
            return {
                "status": "preview",
                "mode": "preview",
                "eligible": 1,
                "applied_records": 0,
            }

    class Application:
        def fundamental_completion_service(self):
            return CompletionService()

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).post(
        "/fundamentals/completion/upload",
        files={
            "file": (
                "Completion.xlsx",
                b"fake-xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"source": "manual_research"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "preview"
    assert calls[0][0] is True
    assert calls[0][1] == ".xlsx"
    assert calls[0][2]["apply"] is False
    assert calls[0][2]["source"] == "manual_research"
    assert calls[0][2]["source_file_name"] == "Completion.xlsx"


def test_fundamental_completion_upload_can_apply(monkeypatch):
    calls = []

    class CompletionService:
        def process_file(self, path, **kwargs):
            calls.append(kwargs)
            return {
                "status": "applied",
                "applied_records": 1,
                "applied_fields": 4,
            }

    class Application:
        def fundamental_completion_service(self):
            return CompletionService()

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).post(
        "/fundamentals/completion/upload",
        files={"file": ("Completion.csv", b"Symbol,ROE\nLUPIN,18\n", "text/csv")},
        data={
            "apply": "true",
            "source": "annual_report",
            "as_of": "2026-10-06",
        },
    )

    assert response.status_code == 200
    assert response.json()["applied_fields"] == 4
    assert calls[0]["apply"] is True
    assert calls[0]["as_of"] == "2026-10-06"


def test_fundamental_completion_history_uses_completion_service(monkeypatch):
    class CompletionService:
        def history(self, symbol, limit=200):
            return [
                {
                    "symbol": symbol.upper(),
                    "field": "roe",
                    "value": 18.5,
                }
            ]

    class Application:
        def fundamental_completion_service(self):
            return CompletionService()

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).get("/fundamentals/lupin/history?limit=10")

    assert response.status_code == 200
    assert response.json()["symbol"] == "LUPIN"
    assert response.json()["history"][0]["field"] == "roe"
