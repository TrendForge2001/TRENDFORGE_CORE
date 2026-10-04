"""Regression coverage for integration readiness semantics."""
from __future__ import annotations

import pandas as pd

from core.integration_health import IntegrationHealth


class _ConfiguredOrchestrator:
    def health(self):
        return {"status": "configured"}


class _HealthyOrchestrator:
    def health(self):
        return {"status": "healthy"}


class _DegradedOrchestrator:
    def health(self):
        return {"status": "degraded"}


def _valid_payload():
    return {
        "symbol": "RELIANCE",
        "df": pd.DataFrame(
            {
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000],
            }
        ),
    }


def test_empty_check_does_not_claim_runtime_health():
    result = IntegrationHealth(orchestrator=_ConfiguredOrchestrator()).check_empty()

    assert result["status"] == "configured"
    assert result["readiness"] == "not_checked"
    assert result["contract"]["validator"] == "available"
    assert result["orchestrator"]["status"] == "configured"


def test_valid_payload_requires_healthy_orchestrator():
    result = IntegrationHealth(orchestrator=_ConfiguredOrchestrator()).check_payload(_valid_payload())

    assert result["status"] == "configured"
    assert result["readiness"]["ready"] is True
    assert result["orchestrator"]["status"] == "configured"


def test_valid_payload_reports_healthy_when_orchestrator_is_healthy():
    result = IntegrationHealth(orchestrator=_HealthyOrchestrator()).check_payload(_valid_payload())

    assert result["status"] == "healthy"


def test_valid_payload_propagates_degraded_orchestrator_state():
    result = IntegrationHealth(orchestrator=_DegradedOrchestrator()).check_payload(_valid_payload())

    assert result["status"] == "degraded"


def test_invalid_payload_remains_not_ready_even_with_healthy_orchestrator():
    payload = _valid_payload()
    payload.pop("df")

    result = IntegrationHealth(orchestrator=_HealthyOrchestrator()).check_payload(payload)

    assert result["status"] == "not_ready"
    assert result["readiness"]["ready"] is False
