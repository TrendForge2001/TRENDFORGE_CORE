"""R72.2 unified Render ASGI composition.

This module is imported only when TRENDFORGE_UNIFIED_UI_ENABLED is enabled.
It preserves the canonical FastAPI Core at its existing routes and mounts the
Streamlit webapp below /app.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import os
from typing import Any

from starlette.applications import Starlette
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route
from streamlit.starlette import App as StreamlitApp


def build_unified_app(core_app: Any) -> Starlette:
    port = str(os.getenv("PORT") or "10000").strip()
    os.environ["TRENDFORGE_API_URL"] = f"http://127.0.0.1:{port}"

    streamlit_app = StreamlitApp("webapp/app.py")
    streamlit_lifespan = streamlit_app.lifespan()
    core_lifespan = core_app.router.lifespan_context

    @asynccontextmanager
    async def unified_lifespan(_app: Starlette):
        async with core_lifespan(core_app):
            async with streamlit_lifespan(streamlit_app):
                yield

    async def homepage(_request):
        return RedirectResponse(url="/app/", status_code=307)

    return Starlette(
        routes=[
            Route("/", endpoint=homepage, methods=["GET"]),
            Mount("/app", app=streamlit_app, name="trendforge-ui"),
            Mount("/", app=core_app, name="trendforge-core"),
        ],
        lifespan=unified_lifespan,
    )


__all__ = ["build_unified_app"]
