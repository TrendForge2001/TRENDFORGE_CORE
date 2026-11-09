"""Isolated browser fixture: synthetic candles, temporary DB, no broker client."""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from api.admin_auth import require_admin_api_key
from api.research_reports_router import research_reports_router
from core.database import initialize_database
from core.unified_render import build_unified_app
from services.research_batches import ResearchBatchManager
from tests.support.research_candles import technical_service

initialize_database(os.environ["DATABASE_PATH"])
technical = technical_service(os.environ["DATABASE_PATH"])
repository = technical.repository


@asynccontextmanager
async def lifespan(core):
    yield
    worker = getattr(core.state, "research_batches", None)
    if worker:
        worker.close(wait=True)
    repository.close()


core = FastAPI(lifespan=lifespan)
core.include_router(
    research_reports_router(
        core,
        lambda: technical,
        manager_factory=lambda value: ResearchBatchManager(
            value, isolated=True, worker_module="tests.support.research_worker"
        ),
    )
)


@core.get("/technical/readiness")
def readiness():
    return {"data_policy": "synthetic_test_fixture"}


@core.get("/workspace/watchlist/{index_name}/constituents")
def constituents(index_name: str):
    return {
        "index": index_name,
        "rows": [
            {"symbol": f"S{i:03d}", "stock_name": f"Synthetic {i}"} for i in range(100)
        ],
    }


app = build_unified_app(core)


@core.post("/fixture/render-batches", dependencies=[Depends(require_admin_api_key)])
def render_batches():
    # Browser fixture only. Real deployment role is configured before app import.
    os.environ["RENDER"] = "true"
    return {"render_resource_limits": True}
