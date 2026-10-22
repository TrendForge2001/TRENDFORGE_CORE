"""Safe API failures without credential-bearing exception text or tracebacks."""
from __future__ import annotations

import logging
import re
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

_LOG = logging.getLogger("trendforge.api.errors")
_SCANNER_READ_PATHS = frozenset({
    "/technical/multi-strategy/readiness",
    "/technical/multi-strategy/results",
    "/technical/multi-strategy/status",
})


def _safe_failure(request: Request, status_code: int, exc: Exception) -> JSONResponse:
    supplied_reference = (exc.headers or {}).get("X-Error-Reference") if isinstance(exc, HTTPException) else None
    reference = (
        supplied_reference
        if isinstance(supplied_reference, str) and re.fullmatch(r"[0-9a-f]{12}", supplied_reference)
        else uuid4().hex[:12]
    )
    scanner_read = request.url.path in _SCANNER_READ_PATHS
    route = request.scope.get("route")
    # Route templates are application constants. Paths, query strings, exception
    # messages and tracebacks can contain provider tokens or private user input.
    _LOG.error(
        "api_request_failed route=%s status=%s error_type=%s reference=%s",
        getattr(route, "path", "<unmatched>"),
        status_code,
        type(exc.__cause__ or exc).__name__,
        reference,
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": (
                "Scanner service temporarily unavailable"
                if scanner_read else "Service temporarily unavailable"
            ),
            "error_code": (
                "SCANNER_READ_UNAVAILABLE" if scanner_read else
                "SERVICE_UNAVAILABLE" if status_code == 503 else
                "INTERNAL_ERROR"
            ),
            "reference": reference,
        },
        headers={"X-Error-Reference": reference},
    )


async def safe_http_error(request: Request, exc: HTTPException):
    if exc.status_code >= 500:
        return _safe_failure(request, exc.status_code, exc)
    # Intentional validation, authentication and missing-resource errors retain
    # their useful contracts and authentication headers.
    return await http_exception_handler(request, exc)


async def scanner_read_error_boundary(request: Request, call_next):
    """Catch failures before ServerErrorMiddleware can log raw tracebacks."""
    try:
        return await call_next(request)
    except Exception as exc:
        status = 503 if request.url.path in _SCANNER_READ_PATHS else 500
        return _safe_failure(request, status, exc)


def install_api_error_boundary(app: FastAPI) -> None:
    """Install once on every factory-created API, including production."""
    if getattr(app.state, "safe_api_errors", False):
        return
    app.state.safe_api_errors = True
    app.add_exception_handler(HTTPException, safe_http_error)
    app.add_middleware(BaseHTTPMiddleware, dispatch=scanner_read_error_boundary)
