"""Regression coverage for integration readiness semantics."""
from __future__ import annotations

from core.integration_health import IntegrationHealth


class _ConfiguredOrchestrator:
    def health(self):
        return {"status": "configured"}


def test_empty_check_does_not_claim_runtime_health():
    result = IntegrationHealth(orchestrator=_ConfiguredOrchestrator()).check_empty()

    assert result["status"] == "configured"
    assert result["readiness"] == "not_checked"
    assert result["contract"]["validator"] == "available"
    assert result["orchestrator"]["status"] == "configured"
