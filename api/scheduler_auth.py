"""Narrow API-key boundary for external operations wake-up calls."""
from __future__ import annotations

import os
import secrets
from typing import Mapping

from fastapi import Header, HTTPException

from api.admin_auth import (
    ADMIN_API_KEY_ENV,
    MIN_ADMIN_API_KEY_LENGTH,
)


SCHEDULER_API_KEY_ENV = "TRENDFORGE_SCHEDULER_API_KEY"
SCHEDULER_API_KEY_HEADER = "X-TrendForge-Scheduler-Key"
MIN_SCHEDULER_API_KEY_LENGTH = 32


def _configured_key(
    environ: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if environ is None else environ
    return str(
        source.get(SCHEDULER_API_KEY_ENV) or ""
    ).strip()


def _admin_key(
    environ: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if environ is None else environ
    return str(
        source.get(ADMIN_API_KEY_ENV) or ""
    ).strip()


def scheduler_security_health(
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    key = _configured_key(environ)
    admin = _admin_key(environ)
    configured = (
        len(key) >= MIN_SCHEDULER_API_KEY_LENGTH
    )
    admin_configured = (
        len(admin) >= MIN_ADMIN_API_KEY_LENGTH
    )
    distinct = not (
        configured
        and admin_configured
        and secrets.compare_digest(key, admin)
    )
    ready = configured and distinct

    return {
        "status": (
            "ready"
            if ready
            else "misconfigured"
            if configured and not distinct
            else "disabled"
        ),
        "scheduler_api_key_configured": configured,
        "distinct_from_admin_api_key": distinct,
        "minimum_key_length": (
            MIN_SCHEDULER_API_KEY_LENGTH
        ),
        "protected_header": SCHEDULER_API_KEY_HEADER,
        "scope": "operations_external_tick_only",
    }


def validate_scheduler_api_key(
    supplied: str | None,
    environ: Mapping[str, str] | None = None,
) -> None:
    expected = _configured_key(environ)
    admin = _admin_key(environ)

    if len(expected) < MIN_SCHEDULER_API_KEY_LENGTH:
        raise HTTPException(
            status_code=503,
            detail=(
                "External scheduler wake-up is disabled "
                f"until {SCHEDULER_API_KEY_ENV} is configured "
                f"with at least {MIN_SCHEDULER_API_KEY_LENGTH} "
                "characters."
            ),
        )

    if (
        len(admin) >= MIN_ADMIN_API_KEY_LENGTH
        and secrets.compare_digest(expected, admin)
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "External scheduler key must be distinct "
                "from the administrative API key."
            ),
        )

    if (
        not supplied
        or not secrets.compare_digest(
            str(supplied),
            expected,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or missing external scheduler API key."
            ),
            headers={"WWW-Authenticate": "ApiKey"},
        )


def require_scheduler_api_key(
    x_trendforge_scheduler_key: str | None = Header(
        default=None,
        alias=SCHEDULER_API_KEY_HEADER,
    ),
) -> None:
    validate_scheduler_api_key(
        x_trendforge_scheduler_key
    )


__all__ = [
    "SCHEDULER_API_KEY_ENV",
    "SCHEDULER_API_KEY_HEADER",
    "MIN_SCHEDULER_API_KEY_LENGTH",
    "scheduler_security_health",
    "validate_scheduler_api_key",
    "require_scheduler_api_key",
]
