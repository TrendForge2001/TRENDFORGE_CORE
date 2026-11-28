"""R72.2 unified Render ASGI composition.

This module is imported only when TRENDFORGE_UNIFIED_UI_ENABLED is enabled.
It preserves the canonical FastAPI Core at its existing routes and mounts the
owner workbench and Streamlit tools below /app.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from streamlit.starlette import App as StreamlitApp

from core.owner_access import OwnerAccessMiddleware
from core.security_headers import SecurityHeaders


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


def build_unified_app(core_app: Any, *, serve_workbench: bool = False) -> Starlette:
    _initialize_report_tables()
    port = str(os.getenv("PORT") or "10000").strip()
    os.environ["TRENDFORGE_API_URL"] = f"http://127.0.0.1:{port}"

    script_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
    streamlit_app = StreamlitApp(str(script_path))
    streamlit_lifespan = streamlit_app.lifespan()
    core_lifespan = core_app.router.lifespan_context
    routes, workbench_assets = [], None
    if serve_workbench:
        from core.workbench_web import workbench_routes

        routes, workbench_assets = workbench_routes(core_app, streamlit_app)
        if workbench_assets:
            logging.getLogger("uvicorn.error").info(
                "TrendForge Workbench mounted at /app/workbench/"
            )

    @asynccontextmanager
    async def unified_lifespan(_app: Starlette):
        from core.report_access import validate_portal_secrets

        validate_portal_secrets()
        logging.getLogger("uvicorn.error").warning("TrendForge host started. Verify paper automation and exit monitor status.")
        async with core_lifespan(core_app), streamlit_lifespan(streamlit_app):
            from services.research_recovery import restore_configured_snapshot
            from services.research_storage_boot import verify_research_storage_boot

            await asyncio.to_thread(verify_research_storage_boot)
            await asyncio.to_thread(restore_configured_snapshot)
            if os.getenv("TRENDFORGE_CLOUD_PAPER_EXECUTION", "").lower() == "true":
                from uuid import uuid4

                from api.app import get_application

                def record_restart():
                    get_application().notification_center_service().system_alert(
                        event_type="paper_host_started",
                        severity="WARNING",
                        title="Paper host restarted",
                        message="Review restored positions and the exit monitor before enabling paper entries.",
                        dedupe_key=f"paper-host-start-{uuid4()}",
                        deliver=False,
                    )

                try:
                    await asyncio.to_thread(record_restart)
                except Exception:
                    logging.getLogger("uvicorn.error").exception("Could not record paper restart notification")
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
                **({"workbench_ui": True} if workbench_assets else {}),
            }
        )

    async def public_health(request):
        if request is not None and "details" in request.query_params:
            # Delegate detailed queries to Core, including its admin middleware.
            return core_app
        return JSONResponse({"status": "ok"})

    async def homepage(_request):
        return RedirectResponse(url="/app/", status_code=307)

    application = Starlette(
        routes=[
            Route(
                "/livez",
                endpoint=render_liveness,
                methods=["GET", "HEAD"],
            ),
            Route(
                "/health",
                endpoint=public_health,
                methods=["GET", "HEAD"],
            ),
            Route("/", endpoint=homepage, methods=["GET"]),
            Route("/app/watchlists", endpoint=homepage, methods=["GET", "HEAD"]),
            Route("/app/technical_scanner", endpoint=homepage, methods=["GET", "HEAD"]),
            *routes,
            Mount("/app", app=streamlit_app, name="trendforge-ui"),
            Mount("/", app=core_app, name="trendforge-core"),
        ],
        lifespan=unified_lifespan,
    )
    application.add_middleware(OwnerAccessMiddleware)
    application.add_middleware(SecurityHeaders)
    return application


__all__ = ["build_unified_app"]
