"""R72.2 unified Render ASGI composition.

This module is imported only when TRENDFORGE_UNIFIED_UI_ENABLED is enabled.
It preserves the canonical FastAPI Core at its existing routes and mounts the
Streamlit webapp below /app.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from streamlit.starlette import App as StreamlitApp


def build_unified_app(core_app: Any) -> Starlette:
    port = str(os.getenv("PORT") or "10000").strip()
    os.environ["TRENDFORGE_API_URL"] = f"http://127.0.0.1:{port}"

    script_path = Path(__file__).resolve().parents[1] / "webapp" / "app.py"
    streamlit_app = StreamlitApp(str(script_path))
    streamlit_lifespan = streamlit_app.lifespan()
    core_lifespan = core_app.router.lifespan_context

    @asynccontextmanager
    async def unified_lifespan(_app: Starlette):
        async with core_lifespan(core_app):
            async with streamlit_lifespan(streamlit_app):
                yield

    async def render_liveness(_request):
        # Render's five-second health probe must never depend on provider,
        # database, scanner, or Streamlit diagnostic work. Detailed service
        # health remains available from the Core production-health endpoints.
        return JSONResponse(
            {
                "service": "TrendForge Core",
                "status": "ok",
                "liveness": "pass",
                "unified_ui": True,
            }
        )

    async def homepage(_request):
        return RedirectResponse(url="/app/", status_code=307)

    return Starlette(
        routes=[
            Route(
                "/livez",
                endpoint=render_liveness,
                methods=["GET", "HEAD"],
            ),
            Route(
                "/health",
                endpoint=render_liveness,
                methods=["GET", "HEAD"],
            ),
            Route("/", endpoint=homepage, methods=["GET"]),
            Mount("/app", app=streamlit_app, name="trendforge-ui"),
            Mount("/", app=core_app, name="trendforge-core"),
        ],
        lifespan=unified_lifespan,
    )


__all__ = ["build_unified_app"]
