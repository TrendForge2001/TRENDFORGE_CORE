"""Tests for dependency-safe runtime health reporting."""
from __future__ import annotations

from config.runtime import runtime_health
from main import health


def test_runtime_health_never_exposes_secret_values():
    report = runtime_health()
    assert "status" in report
    assert isinstance(report["checks"], dict)
    assert all(isinstance(value, bool) for value in report["checks"].values())


def test_application_health_has_runtime_and_components():
    report = health()
    assert "status" in report
    assert "runtime" in report
    assert "indicator_engine" in report
    assert "scoring_engine" in report
