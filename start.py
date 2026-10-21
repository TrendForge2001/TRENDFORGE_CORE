"""Production ASGI entrypoint for TrendForge."""
from __future__ import annotations

from api.app import app
import api.scanner_error_boundary  # noqa: F401 - registers safe scanner middleware

__all__ = ["app"]
