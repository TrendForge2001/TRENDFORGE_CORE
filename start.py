"""Production ASGI entrypoint for TrendForge."""

from __future__ import annotations

from core.boot_diagnostics import startup_import
from services.render_paper_boot import prepare_render_paper

prepare_render_paper()
with startup_import():
    from api.app import app

__all__ = ["app"]
