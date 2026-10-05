"""Minimal executable HTTP API for the TrendForge scanner MVP."""
from __future__ import annotations
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from main import health
from database.database import Database
from database.migrations.run_migrations import run as run_migrations
import providers
from services.default_scanner_factory import build_default_scanner
from services.live_portfolio_sync import LivePortfolioSyncService
from services.paper_trading_runtime import PaperTradingRuntime

logger=logging.getLogger(__name__)


def _resolve_kite_provider():
    candidate = getattr(providers, "kite_provider")
    return getattr(candidate, "kite_provider", candidate)


class _LazyKiteProviderFacade:
    """Read-only broker facade that defers provider construction until use."""

    def is_logged_in(self):
        return _resolve_kite_provider().is_logged_in()

    def holdings(self):
        return _resolve_kite_provider().holdings()

    def positions(self):
        return _resolve_kite_provider().positions()


kite_provider = _LazyKiteProviderFacade()

app=FastAPI(title="TrendForge Core",version="0.1.0")
_scanner=None
_paper_runtime=None

@app.on_event("startup")
def initialize_database():
    global _paper_runtime
    db=Database()
    try:
        run_migrations(db)
    finally:
        db.close()
    _paper_runtime=PaperTradingRuntime()
    _paper_runtime.restore_open()

def get_paper_runtime():
    global _paper_runtime
    if _paper_runtime is None:
        _paper_runtime=PaperTradingRuntime()
        _paper_runtime.restore_open()
    return _paper_runtime

class PaperOrderRequest(BaseModel):
    symbol:str=Field(min_length=1,max_length=30)
    side:str=Field(default="BUY",pattern="^(BUY|SELL|SHORT)$")
    quantity:int=Field(gt=0)
    price:float=Field(gt=0)
    stoploss:float=Field(default=0,ge=0)
    target2:float=Field(default=0,ge=0)
class PaperMonitorRequest(BaseModel):
    quotes:dict[str,float]
class ScanRequest(BaseModel):
    symbols:list[str]=Field(min_length=1,max_length=500)
    capital:float=Field(default=0,ge=0)
    top_n:int=Field(default=20,ge=1,le=100)

def get_scanner():
    global _scanner
    if _scanner is None: _scanner=build_default_scanner()
    return _scanner

@app.get("/health")
def get_health(): return health()
@app.on_event("shutdown")
def shutdown_runtime():
    global _paper_runtime
    if _paper_runtime is not None:
        close = getattr(_paper_runtime, "close", None)
        if callable(close):
            close()
        _paper_runtime = None

@app.post("/scan")
def scan(request:ScanRequest):
    try: return get_scanner().scan(request.symbols,request.capital,request.top_n)
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Scanner request failed"); raise HTTPException(status_code=503,detail="scan unavailable") from exc
@app.get("/portfolio")
def portfolio():
    if not kite_provider.is_logged_in(): raise HTTPException(status_code=503,detail="Kite broker session is not connected")
    service = LivePortfolioSyncService(kite_provider)
    try: return service.sync()
    except Exception as exc:
        logger.exception("Live portfolio synchronization failed"); raise HTTPException(status_code=503,detail="portfolio unavailable") from exc
    finally:
        service.close()
@app.post("/paper/open")
def paper_open(request:PaperOrderRequest):
    try:
        runtime=get_paper_runtime(); trade_id=runtime.open(request)
        return {"status":"opened","trade_id":trade_id,**runtime.snapshot()}
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Paper trade open failed"); raise HTTPException(status_code=503,detail="paper trade unavailable") from exc
@app.post("/paper/monitor")
def paper_monitor(request:PaperMonitorRequest):
    try:
        runtime=get_paper_runtime(); closed=runtime.monitor({str(s).upper():float(p) for s,p in request.quotes.items()})
        return {"status":"monitored","closed":closed,**runtime.snapshot()}
    except Exception as exc:
        logger.exception("Paper trade monitoring failed"); raise HTTPException(status_code=503,detail="paper monitoring unavailable") from exc
@app.get("/paper")
def paper_snapshot(): return get_paper_runtime().snapshot()
