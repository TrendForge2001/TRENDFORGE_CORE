"""Production ASGI entrypoint for TrendForge.

R72.2 can expose the existing FastAPI Core and Streamlit UI from one Render
service. The unified mode is opt-in so the Core can be deployed and verified
before the UI mount is enabled.

Unified routing:
- /          -> redirect to /app/
- /app/*     -> Streamlit web application
- all other paths, including /health and API routes -> existing FastAPI Core
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import os
from typing import Any

from api.app import app as core_app


def _enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_app() -> Any:
    """Return Core-only or unified Core+Streamlit ASGI application."""
    if not _enabled("TRENDFORGE_UNIFIED_UI_ENABLED", False):
        return core_app

    port = str(os.getenv("PORT") or "10000").strip()
    # Streamlit executes the page script server-side. Point its internal API
    # client at the same Uvicorn listener so secrets never need to be copied to
    # a second Render service.
    os.environ["TRENDFORGE_API_URL"] = f"http://127.0.0.1:{port}"

    from starlette.applications import Starlette
    from starlette.responses import RedirectResponse
    from starlette.routing import Mount, Route
    from streamlit.starlette import App as StreamlitApp

    streamlit_app = StreamlitApp("webapp/app.py")
    streamlit_lifespan = streamlit_app.lifespan()
    core_lifespan = core_app.router.lifespan_context

    @asynccontextmanager
    async def unified_lifespan(_app: Starlette):
        # Mounted ASGI applications do not automatically own the parent
        # lifespan. Explicitly enter both runtimes so Core workers and
        # Streamlit's runtime are started and stopped together.
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


app = build_app()

__all__ = ["app", "build_app", "core_app"]
