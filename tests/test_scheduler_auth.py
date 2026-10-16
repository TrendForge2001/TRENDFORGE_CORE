from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.scheduler_auth import (
    SCHEDULER_API_KEY_HEADER,
    scheduler_security_health,
    validate_scheduler_api_key,
)


def test_scheduler_auth_fails_closed_when_not_configured():
    with pytest.raises(HTTPException) as exc:
        validate_scheduler_api_key(None, {})
    assert exc.value.status_code == 503


def test_scheduler_auth_rejects_wrong_key_and_accepts_match():
    environ = {
        "TRENDFORGE_SCHEDULER_API_KEY": "s" * 40,
        "TRENDFORGE_ADMIN_API_KEY": "a" * 40,
    }

    with pytest.raises(HTTPException) as exc:
        validate_scheduler_api_key(
            "wrong",
            environ,
        )
    assert exc.value.status_code == 401

    validate_scheduler_api_key(
        "s" * 40,
        environ,
    )


def test_scheduler_key_must_be_distinct_from_admin_key():
    environ = {
        "TRENDFORGE_SCHEDULER_API_KEY": "x" * 40,
        "TRENDFORGE_ADMIN_API_KEY": "x" * 40,
    }

    with pytest.raises(HTTPException) as exc:
        validate_scheduler_api_key(
            "x" * 40,
            environ,
        )

    assert exc.value.status_code == 503
    assert "distinct" in str(exc.value.detail)


def test_scheduler_security_health_never_exposes_secret():
    key = "z" * 40
    health = scheduler_security_health(
        {
            "TRENDFORGE_SCHEDULER_API_KEY": key,
            "TRENDFORGE_ADMIN_API_KEY": "a" * 40,
        }
    )

    assert health["status"] == "ready"
    assert health["scheduler_api_key_configured"] is True
    assert health["distinct_from_admin_api_key"] is True
    assert health["protected_header"] == SCHEDULER_API_KEY_HEADER
    assert health["scope"] == "operations_external_tick_only"
    assert key not in str(health)
