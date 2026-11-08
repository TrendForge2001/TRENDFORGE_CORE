"""Isolated browser fixture: synthetic candles, temporary DB, no broker client."""

import os
from contextlib import asynccontextmanager
from types import SimpleNamespace

import numpy as np
import pandas as pd
from fastapi import FastAPI

from api.research_reports_router import research_reports_router
from core.database import initialize_database
from core.unified_render import build_unified_app
from database.repositories.backtest_results import BacktestResultsRepository
from services.technical_trading_service import TechnicalTradingService

initialize_database(os.environ["DATABASE_PATH"])
index = pd.bdate_range("2024-01-01", periods=500, tz="Asia/Kolkata")
x = np.arange(500)
close = 100 + x * 0.04 + np.sin(x / 9) * 5 + np.sin(x / 2) * 0.5
raw = pd.DataFrame(
    {
        "open": close - 0.15,
        "high": close + 0.8,
        "low": close - 0.9,
        "close": close,
        "volume": 2000.0 + (x % 17) * 100,
    },
    index=index,
)
market = SimpleNamespace(
    batch_candles_with_errors=lambda symbols, **kwargs: (
        {symbol: raw.copy() for symbol in symbols},
        {},
    )
)
repository = BacktestResultsRepository(db_path=os.environ["DATABASE_PATH"])
technical = TechnicalTradingService(market_data=market, repository=repository)


@asynccontextmanager
async def lifespan(core):
    yield
    worker = getattr(core.state, "research_batches", None)
    if worker:
        worker.close(wait=True)
    repository.close()


core = FastAPI(lifespan=lifespan)
core.include_router(research_reports_router(core, lambda: technical))


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
