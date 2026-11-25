"""Read-only market evidence and strategy catalog for the private workbench."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from api.admin_auth import require_admin_api_key
from scanner.approved_strategies import active, exit_only
from scanner.portfolio_policy import number
from scanner.strategy_horizons import HORIZONS, horizon_strategies
from scanner.strategy_registry import REGISTRY_VERSION, SCANNER_CHOICE_IDS, list_strategies


def workbench_router(technical_getter):
    router = APIRouter(prefix="/workbench", dependencies=[Depends(require_admin_api_key)])

    @router.get("/catalog")
    def catalog():
        choices = {}
        for horizon in HORIZONS:
            for definition in horizon_strategies(horizon).values():
                key = definition["strategy_id"]
                choices.setdefault(key, []).append(horizon)
        rows = []
        for definition in list_strategies():
            key = definition["strategy_id"]
            status = definition["implementation_status"]
            lifecycle = (
                "PRODUCTION"
                if status == "production"
                else "PAPER"
                if definition["paper_eligible"] and (active(key) or status == "staged_paper_execution")
                else "RESEARCH"
            )
            horizons = choices.get(key, [])
            backtest_horizons = [
                horizon for horizon in horizons
                if not active(key) or not exit_only(key, "intraday" if horizon == "intraday" else "swing")
            ]
            rows.append({
                **definition,
                "lifecycle": lifecycle,
                "horizons": horizons,
                "backtest_horizons": backtest_horizons,
                "scanner": key in SCANNER_CHOICE_IDS,
                "policy_overrides": active(key),
            })
        return {"version": REGISTRY_VERSION, "strategies": rows}

    def history(symbol, interval, start, end):
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        if (start and end and start > end) or (start and start > today) or (end and end > today):
            raise HTTPException(422, "Choose a valid historical candle window")
        warmup = 390 if interval == "1d" else 22
        days = (today - (start or end or today)).days + warmup
        if days > 2250:
            raise HTTPException(422, "The requested candle window is outside supported history")
        try:
            technical = technical_getter()
            frame = technical.market_data.candles(symbol, period=f"{days}d", interval=interval)
            frame = technical._completed_bars(frame, interval=interval)
        except Exception:
            raise HTTPException(503, "Completed market candles are temporarily unavailable") from None
        candles = []
        for stamp, row in frame.iterrows():
            stamp = technical._as_ist(stamp)
            if stamp is None or (end and stamp.date() > end):
                continue
            values = {key: number(row.get(key)) for key in ("open", "high", "low", "close", "volume")}
            if all(values[key] is not None for key in ("open", "high", "low", "close")):
                candles.append({"date": stamp.isoformat(), **values})
        return candles

    @router.get("/candles/{symbol}")
    def candles(
        symbol: str,
        interval: str = Query(default="1d", pattern=r"^(1d|15m)$"),
        start: date | None = None,
        end: date | None = None,
    ):
        import re

        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._&-]{0,29}", symbol) or ".." in symbol:
            raise HTTPException(422, "Invalid NSE symbol")
        return {"candles": history(symbol, interval, start, end)}

    @router.get("/benchmark")
    def benchmark(start: date | None = None, end: date | None = None):
        return {"candles": history("NIFTY 50", "1d", start, end)}

    return router
