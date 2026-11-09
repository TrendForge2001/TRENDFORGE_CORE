"""Synthetic local paper book for UI acceptance. No broker client is constructed."""

import os
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException

from api.admin_auth import require_admin_api_key
from core.database import initialize_database
from core.unified_render import build_unified_app
from database.database import Database
from database.repositories.trade_repository import TradeRepository
from services.paper_auto_entry_service import PaperAutoEntryService
from services.paper_trading_runtime import PaperTradingRuntime
from services.paper_trading_service import PaperTradingService

NOW = datetime(2026, 11, 9, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
initialize_database(os.environ["DATABASE_PATH"])
database = Database(os.environ["DATABASE_PATH"])
repository = TradeRepository(db=database)
paper = PaperTradingService(
    PaperTradingRuntime(trades=repository), enabled=True, environment_kill_switch=False
)
paper.open(
    SimpleNamespace(
        symbol="TCS",
        side="BUY",
        quantity=1,
        price=100,
        stoploss=90,
        target2=120,
    ),
    now=NOW,
)
auto = PaperAutoEntryService(paper, enabled=True)
state = {"enabled": False, "unavailable": False}


@asynccontextmanager
async def lifespan(_app):
    yield
    database.close()


core = FastAPI(lifespan=lifespan, dependencies=[Depends(require_admin_api_key)])


def available():
    if state["unavailable"]:
        raise HTTPException(503, "Synthetic status outage")


@core.get("/workspace/paper-portfolio")
def portfolio():
    available()
    return {"portfolio": paper.snapshot()}


@core.get("/paper/readiness")
def readiness():
    available()
    return {**paper.health(), "automatic_monitor": {"enabled": True, "running": True}}


@core.get("/paper/automation")
def automation():
    available()
    return {
        "enabled": state["enabled"],
        "phase": "watching_market" if state["enabled"] else "off",
        "worker_running": True,
        "blockers": ["paper_kill_switch_active"] if paper.kill_switch else [],
        "universe": "NIFTY 500",
        "target_symbols": ["TCS"],
        "target_strategy_ids": None,
        "strategies": [],
        "account_policy": auto.health(),
    }


@core.put("/paper/automation")
def configure(body: dict):
    if (
        body["enabled"]
        and os.getenv("RENDER") == "true"
        and body.get("confirm_render_executor") is not True
    ):
        raise HTTPException(422, "Confirm the PC executor is stopped")
    state["enabled"] = body["enabled"]
    return {"enabled": state["enabled"]}


@core.post("/paper/kill-switch")
def kill(body: dict):
    return paper.set_runtime_kill_switch(body["enabled"])


@core.post("/fixture/mark")
def mark():
    paper.monitor({"TCS": 110}, now=NOW)
    return {"status": "marked"}


@core.post("/fixture/unavailable")
def unavailable():
    state["unavailable"] = True
    return {"status": "unavailable"}


@core.get("/fixture/status")
def fixture_status():
    return {"kill_switch": paper.kill_switch, "automation_enabled": state["enabled"]}


app = build_unified_app(core)
