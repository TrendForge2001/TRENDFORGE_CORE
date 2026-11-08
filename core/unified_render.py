"""R72.2 unified Render ASGI composition.

This module is imported only when TRENDFORGE_UNIFIED_UI_ENABLED is enabled.
It preserves the canonical FastAPI Core at its existing routes and mounts the
Streamlit webapp below /app.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from streamlit.starlette import App as StreamlitApp


@lru_cache(maxsize=1)
def _initialize_report_tables() -> None:
    # These libraries do some native initialization while holding the GIL.
    # Finish it before the listener becomes healthy, rather than on the first
    # Reports navigation while Render's five-second probes are already active.
    import pandas as pd
    import pyarrow as pa

    frame = pd.DataFrame({"value": [0.0]})
    frame.style.to_html()
    table = pa.Table.from_pandas(frame)
    with (
        pa.BufferOutputStream() as stream,
        pa.ipc.new_stream(stream, table.schema) as writer,
    ):
        writer.write_table(table)


def build_unified_app(core_app: Any) -> Starlette:
    _initialize_report_tables()
    port = str(os.getenv("PORT") or "10000").strip()
    os.environ["TRENDFORGE_API_URL"] = f"http://127.0.0.1:{port}"

    script_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
    streamlit_app = StreamlitApp(str(script_path))
    streamlit_lifespan = streamlit_app.lifespan()
    core_lifespan = core_app.router.lifespan_context

    @asynccontextmanager
    async def unified_lifespan(_app: Starlette):
        async with core_lifespan(core_app), streamlit_lifespan(streamlit_app):
            from services.research_recovery import restore_configured_snapshot

            await asyncio.to_thread(restore_configured_snapshot)
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
