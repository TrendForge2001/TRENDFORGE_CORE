"""Regression contracts for HTTP 502 handling in R71 staging UI."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_command_center_stops_after_failed_health_check():
    code = (ROOT / "webapp" / "pages" / "dashboard.py").read_text(encoding="utf-8")
    preflight = code.index('health, health_error = safe_get("/health")')
    stop = code.index("st.stop()", preflight)
    next_request = code.index('paper, paper_error = safe_get("/paper/readiness")')
    assert preflight < stop < next_request
    assert 'Configured backend: {client.base_url}' in code


def test_scanner_preflight_runs_before_post_request():
    code = (ROOT / "webapp" / "pages" / "scanner.py").read_text(encoding="utf-8")
    check = code.index('client.get_json("/health", timeout=30)')
    post = code.index('result = client.post_json(')
    assert check < post
    assert "Backend preflight failed" in code
    assert "No scan POST was sent" in code
    assert "Check backend audit for failed run" in code


def test_gateway_html_is_not_shown_as_raw_page():
    code = (ROOT / "webapp" / "ui.py").read_text(encoding="utf-8")
    assert "exc.status_code in {502, 504}" in code
    assert '"<!doctype html" in detail.lower()' in code
    assert "raw gateway HTML has been hidden" in code


def test_fundamental_writes_require_verified_persistent_storage():
    page = (ROOT / "webapp" / "pages" / "fundamentals.py").read_text(encoding="utf-8")
    ui = (ROOT / "webapp" / "ui.py").read_text(encoding="utf-8")
    assert 'client.get_json("/production/health", timeout=20)' in page
    assert 'storage_health.get("verified_persistent")' in page
    assert "disabled=completion_upload is None or not storage_verified" in page
    assert "disabled=bulk_upload is None or not bulk_run_id or not storage_verified" in page
    assert "disabled=uploaded is None or not storage_verified" in page
    assert "disabled=not storage_verified" in page
    assert "database storage is not verified persistent" in ui
    assert "The completion-upload endpoint also rejects read-only previews" in ui
