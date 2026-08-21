"""Canonical FastAPI application boundary for TrendForge Core."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.application_factory import ApplicationFactory


class ScanRequest(BaseModel):
    symbols: list[str] = Field(min_length=1)
    period: str = "6mo"
    interval: str = "1d"
    capital: float = 0.0
    top_n: int = Field(default=20, ge=1, le=500)


app = FastAPI(title="TrendForge Core API", version="1.0.0")


def get_application() -> ApplicationFactory:
    return ApplicationFactory()


def get_scanner_service():
    return get_application().scanner_service()


@app.get("/")
def root() -> dict[str, Any]:
    return {"service": "TrendForge Core", "status": "ok"}


@app.get("/health")
def health() -> dict[str, Any]:
    return get_application().health()


@app.get("/scan/{symbol}")
def scan_symbol(symbol: str, period: str = "6mo", interval: str = "1d", capital: float = 0.0) -> dict[str, Any]:
    try:
        return get_scanner_service().scan(symbol, period=period, interval=interval, capital=capital)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/scan")
def scan(request: ScanRequest) -> dict[str, Any]:
    try:
        return get_scanner_service().scan_many(
            request.symbols,
            period=request.period,
            interval=request.interval,
            capital=request.capital,
            top_n=request.top_n,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = ["app", "get_application", "get_scanner_service"]
