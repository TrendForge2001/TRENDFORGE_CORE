"""Minimal executable HTTP API for the TrendForge scanner MVP."""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from main import health
from database.database import Database
from database.migrations.run_migrations import run as run_migrations
from providers.kite_provider import kite_provider
from services.default_scanner_factory import build_default_scanner
from services.live_portfolio_sync import LivePortfolioSyncService

logger = logging.getLogger(__name__)
app = FastAPI(title="TrendForge Core", version="0.1.0")
_scanner = None


@app.on_event("startup")
def initialize_database():
    db = Database()
    try:
        run_migrations(db)
    finally:
        db.close()


class ScanRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=500)
    capital: float = Field(default=0, ge=0)
    top_n: int = Field(default=20, ge=1, le=100)


def get_scanner():
    global _scanner
    if _scanner is None:
        _scanner = build_default_scanner()
    return _scanner


@app.get("/health")
def get_health():
    return health()


@app.post("/scan")
def scan(request: ScanRequest):
    try:
        return get_scanner().scan(request.symbols, request.capital, request.top_n)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Scanner request failed")
        raise HTTPException(status_code=503, detail="scan unavailable") from exc


@app.get("/portfolio")
def portfolio():
    if not kite_provider.is_logged_in():
        raise HTTPException(status_code=503, detail="Kite broker session is not connected")
    try:
        return LivePortfolioSyncService(kite_provider).sync()
    except Exception as exc:
        logger.exception("Live portfolio synchronization failed")
        raise HTTPException(status_code=503, detail="portfolio unavailable") from exc
