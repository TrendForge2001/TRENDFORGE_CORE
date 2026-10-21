"""Production ASGI entrypoint for TrendForge."""
from __future__ import annotations

from core.boot_diagnostics import startup_import

with startup_import():
    from api.app import app
    import api.scanner_error_boundary  # noqa: F401 - registers safe scanner middleware

__all__ = ["app"]
