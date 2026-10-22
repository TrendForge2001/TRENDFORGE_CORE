"""Production ASGI entrypoint for TrendForge."""
from __future__ import annotations

from core.boot_diagnostics import startup_import

with startup_import():
    from api.app import app

__all__ = ["app"]
