"""Production ASGI entrypoint for TrendForge.

R72.5.8.1: Normalize unexpected scanner-read errors without exposing internals.
"""
from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api.app import app

_LOG = logging.getLogger("trendforge.scanner.api")
_SCANNER_READ_PATHS = frozenset({
    "/technical/multi-strategy/readiness",
    "/technical/multi-strategy/results",
    "/technical/multi-strategy/status",
})


async def scanner_read_error_boundary(request: Request, call_next):
    """Fail closed for scanner read endpoints; do not intercept other routes."""
    if request.url.path not in _SCANNER_READ_PATHS:
        return await call_next(request)
    try:
        return await call_next(request)
    except Exception:
        reference = uuid4().hex[:12]
        _LOG.exception(
            "scanner_read_failed path=%s reference=%s",
            request.url.path, reference,
        )
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Scanner service temporarily unavailable",
                "error_code": "SCANNER_READ_UNAVAILABLE",
                "reference": reference,
            },
        )


app.add_middleware(BaseHTTPMiddleware, dispatch=scanner_read_error_boundary)

__all__ = ["app"]
