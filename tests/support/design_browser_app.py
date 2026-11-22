"""All-page design fixture: synthetic data only, no broker or external feeds."""

import os
from types import SimpleNamespace

from api.big_shark_router import big_shark_router
from api.research_reports_router import research_reports_router
from services.research_batches import ResearchBatchManager
from tests.support.paper_browser_app import app as app
from tests.support.paper_browser_app import core
from tests.support.public_feed_fixtures import SyntheticDaily, SyntheticPublic
from tests.support.weekly_browser_market import technical_service

technical = technical_service(os.environ["DATABASE_PATH"])
core.include_router(
    research_reports_router(
        core,
        lambda: technical,
        manager_factory=lambda value: ResearchBatchManager(value, isolated=False),
    )
)
core.include_router(
    big_shark_router(
        lambda: SimpleNamespace(market_data=SyntheticDaily()),
        public_provider_getter=SyntheticPublic,
    )
)


@core.get("/technical/readiness")
def technical_readiness():
    return {"data_policy": "synthetic_design_fixture"}


@core.get("/workspace/watchlist/{name}/constituents")
def constituents(name: str):
    return {
        "index": name,
        "source": "Synthetic design fixture",
        "rows": [
            {
                "symbol": f"S{i:03d}",
                "stock_name": f"Example company {i}",
                "sector": "Example sector",
            }
            for i in range(20)
        ],
    }


@core.get("/workspace/watchlist/{name}")
def quotes(name: str):
    return {
        "index": name,
        "source": "Synthetic design fixture",
        "quotes_available": False,
        "rows": [],
        "unavailable_symbols": [f"S{i:03d}" for i in range(20)],
    }


@core.get("/workspace/kite-session")
def kite_session():
    return {
        "status": "synthetic preview",
        "authenticated": True,
        "broker_orders_allowed": False,
        "holdings": [],
        "positions": {"net": [], "day": []},
        "orders": [],
        "margins": {},
    }
