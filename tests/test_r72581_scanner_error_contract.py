"""R72.5.8.1 scanner API regression contract.

This test documents the requirement that service errors on the results and
status endpoints become safe 503 responses rather than unhandled HTTP 500.
"""
from pathlib import Path


def test_scanner_read_endpoints_guard_service_failures():
    source = Path("api/app.py").read_text(encoding="utf-8")
    for route, following in (
        ('@app.get("/technical/multi-strategy/results")', '@app.get("/technical/multi-strategy/status")'),
        ('@app.get("/technical/multi-strategy/status")', '@app.post('),
    ):
        section = source.split(route, 1)[1].split(following, 1)[0]
        assert "except Exception as exc:" in section
        assert "status_code=503" in section
