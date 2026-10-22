"""Public diagnostics retain readiness without forwarding arbitrary provider data."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from api.public_health import public_health


def test_public_health_preserves_component_readiness_without_sensitive_details():
    sentinel = "public-health-credential-sentinel"
    component = {
        "status": "degraded", "error": sentinel, "path": f"/private/{sentinel}",
        "file": sentinel, "source_url": f"https://provider.invalid?token={sentinel}",
    }
    report = {
        "status": "degraded",
        "configuration": {"status": "ok", "kite_configured": True, "kite_authenticated": False},
        "database": component,
        "market_data": component,
        "enrichment": component,
        "enrichment_snapshot": component,
        "fundamental_import": component,
        "scanner": {**component, "runtime_status": "failed"},
        "execution": {"paper_trading": {**component, "status": "locked"}, "secret": sentinel},
        "observability": {"scan_run_audit": component},
        "universe": {"nifty500": component, "provider": component},
        "domain_providers": {"news": sentinel},
        "extra": sentinel,
    }
    original = deepcopy(report)

    result = public_health(report)

    assert result["status"] == "degraded"
    assert result["configuration"] == {
        "status": "ok", "kite_configured": True, "kite_authenticated": False,
    }
    assert result["scanner"] == {"status": "degraded", "runtime_status": "failed"}
    assert result["execution"]["paper_trading"]["status"] == "locked"
    assert result["universe"]["nifty500"]["status"] == "degraded"
    assert result["observability"]["scan_run_audit"] == {"status": "degraded"}
    assert sentinel not in json.dumps(result)
    assert report == original


@pytest.mark.parametrize("invalid", ["token=secret", ["healthy"], {"secret": "secret"}, 1, None])
def test_public_health_rejects_arbitrary_status_values_and_nonboolean_flags(invalid):
    result = public_health({
        "status": invalid,
        "database": {"status": invalid},
        "scanner": {"runtime_status": invalid},
        "configuration": {"kite_configured": invalid, "kite_authenticated": invalid},
        "universe": {"nifty500": {"status": invalid}},
    })

    assert result["status"] == "unknown"
    assert result["database"] == {"status": "unknown"}
    assert result["scanner"]["runtime_status"] == "unknown"
    assert result["configuration"] == {"status": "unknown"}
    assert result["universe"]["nifty500"] == {"status": "unknown"}


def test_public_health_handles_missing_or_invalid_component_shapes():
    result = public_health({"status": "healthy", "database": "unexpected", "execution": []})
    assert result["status"] == "healthy"
    assert result["database"] == {"status": "unknown"}
    assert result["execution"]["paper_trading"] == {"status": "unknown"}
    assert public_health(None)["status"] == "unknown"
