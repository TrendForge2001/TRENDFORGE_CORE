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


@core.post("/fixture/workflow/seed")
def seed_scanner_workflow():
    from database.repositories.research_batches import ResearchBatchRepository
    from services.research_report import build_report
    from services.research_storage import complete_batch, report_archive

    repository = ResearchBatchRepository(technical.repository.db)
    key = "workflow-browser-seed"
    if repository.get(key):
        return {"seeded": True}
    request = {
        "horizon": "short_term",
        "strategy_id": "tf_swing_ema20_50_rsi_volume",
        "stock_list": "NIFTY 50",
        "symbols": ["TCS", "INFY", "RELIANCE"],
    }
    repository.create(key, "scan", request)
    repository.start(key)
    report = build_report(
        {
            "run_id": key,
            "strategy_id": request["strategy_id"],
            "mode": "swing",
            "interval": "1d",
            "period": "2y",
            "results": [
                {
                    "symbol": symbol,
                    "signal": signal,
                    "side": "LONG",
                    "score": 80,
                    "entry": 100,
                    "stoploss": 95,
                    "target2": 110,
                    "data_status": "READY",
                    "indicators": {},
                }
                for symbol, signal in (
                    ("TCS", "BUY"),
                    ("INFY", "EXIT"),
                    ("RELIANCE", "WAIT"),
                )
            ],
        },
        kind="scan",
        horizon="short_term",
        stock_list="NIFTY 50",
    )
    complete_batch(
        repository, report_archive(technical.repository.db.db_path), key, report
    )
    return {"seeded": True, "synthetic": True, "orders_submitted": 0}


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
