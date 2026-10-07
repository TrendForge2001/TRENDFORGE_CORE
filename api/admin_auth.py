"""Administrative API-key boundary for privileged TrendForge mutations."""
from __future__ import annotations

import os
import secrets
from typing import Mapping

from fastapi import Header, HTTPException


ADMIN_API_KEY_ENV = "TRENDFORGE_ADMIN_API_KEY"
ADMIN_API_KEY_HEADER = "X-TrendForge-Admin-Key"
MIN_ADMIN_API_KEY_LENGTH = 32


def _configured_key(environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    return str(source.get(ADMIN_API_KEY_ENV) or "").strip()


def admin_security_health(
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    key = _configured_key(environ)
    configured = len(key) >= MIN_ADMIN_API_KEY_LENGTH
    return {
        "status": "ready" if configured else "disabled",
        "admin_api_key_configured": configured,
        "minimum_key_length": MIN_ADMIN_API_KEY_LENGTH,
        "protected_header": ADMIN_API_KEY_HEADER,
    }


def require_admin_api_key(
    x_trendforge_admin_key: str | None = Header(
        default=None,
        alias=ADMIN_API_KEY_HEADER,
    ),
) -> None:
    """Fail closed unless a sufficiently strong configured key matches."""
    expected = _configured_key()
    if len(expected) < MIN_ADMIN_API_KEY_LENGTH:
        raise HTTPException(
            status_code=503,
            detail=(
                "Administrative mutations are disabled until "
                f"{ADMIN_API_KEY_ENV} is configured with at least "
                f"{MIN_ADMIN_API_KEY_LENGTH} characters."
            ),
        )

    supplied = str(x_trendforge_admin_key or "")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing administrative API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )


__all__ = [
    "ADMIN_API_KEY_ENV",
    "ADMIN_API_KEY_HEADER",
    "MIN_ADMIN_API_KEY_LENGTH",
    "admin_security_health",
    "require_admin_api_key",
]
