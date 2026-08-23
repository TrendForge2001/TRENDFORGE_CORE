"""Canonical FastAPI application boundary for TrendForge Core."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from core.application_factory import ApplicationFactory


class ScanRequest(BaseModel):
    symbols: list[str] = Field(min_length=1)
    period: str = "6mo"
    interval: str = "1d"
    capital: float = 0.0
    top_n: int = Field(default=20, ge=1, le=500)


def create_app(application_factory: ApplicationFactory | None = None) -> FastAPI:
    """Create an application with one explicit composition root per ASGI app."""
    app = FastAPI(title="TrendForge Core API", version="1.0.0")
    app.state.application_factory = application_factory or ApplicationFactory()

    def get_application(request: Request) -> ApplicationFactory:
        return request.app.state.application_factory

    def get_scanner_service(application: ApplicationFactory = Depends(get_application)):
        return application.scanner_service()

    @app.get("/")
    def root() -> dict[str, Any]:
        return {"service": "TrendForge Core", "status": "ok"}

    @app.get("/health")
    def health(application: ApplicationFactory = Depends(get_application)) -> dict[str, Any]:
        return application.health()

    @app.get("/scan/{symbol}")
    def scan_symbol(
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
        capital: float = 0.0,
        scanner_service=Depends(get_scanner_service),
    ) -> dict[str, Any]:
        try:
            return scanner_service.scan(symbol, period=period, interval=interval, capital=capital)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/scan")
    def scan(request: ScanRequest, scanner_service=Depends(get_scanner_service)) -> dict[str, Any]:
        try:
            return scanner_service.scan_many(
                request.symbols,
                period=request.period,
                interval=request.interval,
                capital=request.capital,
                top_n=request.top_n,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


app = create_app()


def get_application(request: Request) -> ApplicationFactory:
    return request.app.state.application_factory


__all__ = ["app", "create_app", "get_application"]
