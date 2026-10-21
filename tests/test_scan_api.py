"""Canonical scan API boundary tests.

The former api.scan_api module was retired; production serves api.app via start.
These tests intentionally avoid Kite, order submission and external providers.
"""
from pathlib import Path

from start import app


def test_production_app_is_asgi():
    assert callable(app)


def test_legacy_scan_api_is_explicitly_deprecated():
    source = Path("api/scan_api.py").read_text(encoding="utf-8")
    assert "deprecated stub" in source
    assert "fully implemented in api/app.py" in source


def test_canonical_api_defines_required_scan_and_portfolio_routes():
    source = Path("api/app.py").read_text(encoding="utf-8")
    for path in (
        '"/scan"',
        '"/technical/multi-strategy/run"',
        '"/technical/multi-strategy/results"',
        '"/technical/multi-strategy/status"',
        '"/portfolio"',
    ):
        assert path in source


def test_scan_request_requires_nonempty_symbols():
    from api.app import ScanRequest
    from pydantic import ValidationError
    import pytest

    with pytest.raises(ValidationError):
        ScanRequest(symbols=[])
