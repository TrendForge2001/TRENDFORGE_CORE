from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient

from api.app import create_app
from api.production_runtime import (
    _protected_admin_request,
    _requires_persistent_storage,
)


class FakeBulkService:
    VERSION = "R69.5"

    def __init__(self):
        self.calls = []

    def readiness(self):
        return {
            "version": "R69.5",
            "status": "ready",
            "stage_sizes": [25, 50, 100, 250, 500],
            "preview_required_before_apply": True,
        }

    def history(self, *, limit=50):
        return [
            {
                "run_id": "bulk-1",
                "status": "in_progress",
                "next_offset": 25,
                "total_rows": 100,
            }
        ][:limit]

    def get(self, run_id):
        if run_id == "missing":
            return None
        return {
            "run_id": run_id,
            "status": "previewed",
            "next_offset": 25,
            "total_rows": 100,
        }

    def process_file(
        self,
        path,
        *,
        run_id=None,
        stage_size=25,
        apply=False,
        source=None,
        as_of=None,
        sheet_name="Completion",
        source_file_name=None,
    ):
        self.calls.append(
            {
                "run_id": run_id,
                "stage_size": stage_size,
                "apply": apply,
                "source": source,
                "as_of": as_of,
                "sheet_name": sheet_name,
                "source_file_name": source_file_name,
            }
        )
        return {
            "version": "R69.5",
            "status": "preview_ready",
            "run_id": run_id or "generated",
        }


class Factory:
    def __init__(self):
        self.bulk = FakeBulkService()

    def fundamental_bulk_ingestion_service(self):
        return self.bulk


def test_bulk_readiness_and_run_routes():
    client = TestClient(create_app(Factory()))

    readiness = client.get("/fundamentals/bulk/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["version"] == "R69.5"
    assert readiness.json()["stage_sizes"] == [25, 50, 100, 250, 500]

    history = client.get("/fundamentals/bulk/runs?limit=10")
    assert history.status_code == 200
    assert history.json()["count"] == 1

    detail = client.get("/fundamentals/bulk/runs/bulk-1")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == "bulk-1"

    missing = client.get("/fundamentals/bulk/runs/missing")
    assert missing.status_code == 404


def test_bulk_upload_projects_form_contract():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post(
        "/fundamentals/bulk/upload",
        files={
            "file": (
                "fundamentals.csv",
                BytesIO(b"Symbol,ROCE\nAAA,20\n"),
                "text/csv",
            )
        },
        data={
            "run_id": "bulk-55",
            "stage_size": "50",
            "apply": "false",
            "source": "curated",
            "as_of": "2026-09-30",
            "sheet": "Completion",
        },
    )

    assert response.status_code == 200
    assert response.json()["version"] == "R69.5"
    assert factory.bulk.calls == [
        {
            "run_id": "bulk-55",
            "stage_size": 50,
            "apply": False,
            "source": "curated",
            "as_of": "2026-09-30",
            "sheet_name": "Completion",
            "source_file_name": "fundamentals.csv",
        }
    ]


def test_bulk_upload_is_admin_and_persistence_protected():
    assert _protected_admin_request(
        "POST",
        "/fundamentals/bulk/upload",
    )
    assert _requires_persistent_storage(
        "POST",
        "/fundamentals/bulk/upload",
    )
    assert not _protected_admin_request(
        "GET",
        "/fundamentals/bulk/readiness",
    )
    assert not _protected_admin_request(
        "GET",
        "/fundamentals/bulk/runs",
    )
