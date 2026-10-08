from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.admin_auth import (
    ADMIN_API_KEY_HEADER,
    admin_security_health,
    validate_admin_api_key,
)


def test_admin_auth_fails_closed_when_key_not_configured():
    with pytest.raises(HTTPException) as exc:
        validate_admin_api_key(None, {})
    assert exc.value.status_code == 503


def test_admin_auth_rejects_wrong_key_and_accepts_match():
    environ = {"TRENDFORGE_ADMIN_API_KEY": "a" * 40}
    with pytest.raises(HTTPException) as exc:
        validate_admin_api_key("wrong", environ)
    assert exc.value.status_code == 401
    validate_admin_api_key("a" * 40, environ)


def test_admin_security_health_never_exposes_secret():
    health = admin_security_health(
        {"TRENDFORGE_ADMIN_API_KEY": "b" * 40}
    )
    assert health["status"] == "ready"
    assert health["admin_api_key_configured"] is True
    assert health["protected_header"] == ADMIN_API_KEY_HEADER
    assert "b" * 40 not in str(health)
