"""Canonical FastAPI application boundary for TrendForge Core."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core.application_factory import ApplicationFactory, build_application_factory
from core.database import initialize_database


class ScanRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=500)
    period: str = "6mo"
    interval: str = "1d"
    capital: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    top_n: int = Field(default=20, ge=1, le=500)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        normalized = [str(symbol).strip().upper() for symbol in value]
        if any(not symbol for symbol in normalized):
            raise ValueError("symbols must not contain empty values")
        return normalized


_APPLICATION_FACTORY: ApplicationFactory | None = None


def get_application() -> ApplicationFactory:
    global _APPLICATION_FACTORY
    if _APPLICATION_FACTORY is None:
        _APPLICATION_FACTORY = build_application_factory()
    return _APPLICATION_FACTORY


def get_scanner_service():
    return get_application().scanner_service()


def create_app(
    application_factory: ApplicationFactory | None = None,
    *,
    database_initializer: Callable[[], dict[str, Any]] | None = None,
) -> FastAPI:
    global _APPLICATION_FACTORY
    factory = application_factory or build_application_factory()
    if application_factory is None:
        _APPLICATION_FACTORY = factory

    def current_application():
        return factory if application_factory is not None else get_application()

    def current_scanner_service():
        return factory.scanner_service() if application_factory is not None else get_scanner_service()

    initializer = database_initializer or initialize_database

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _app.state.database = initializer()
        _app.state.fundamentals_import = (
            current_application().import_fundamentals_if_configured()
        )
        yield

    app = FastAPI(title="TrendForge Core API", version="1.0.0", lifespan=lifespan)
    app.state.application_factory = factory

    @app.get("/")
    def root() -> dict[str, Any]:
        return {"service": "TrendForge Core", "status": "ok"}

    @app.get("/health")
    def health() -> dict[str, Any]:
        try:
            return current_application().health()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/scan/{symbol}")
    def scan_symbol(symbol: str, period: str = "6mo", interval: str = "1d",
                    capital: float = Query(default=0.0, ge=0, allow_inf_nan=False)) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        if not symbol:
            raise HTTPException(status_code=422, detail="Symbol is required")
        try:
            result = current_scanner_service().scan(
                symbol, period=period, interval=interval, capital=capital
            )
            if not isinstance(result, dict):
                raise ValueError("Scanner returned an invalid result contract")
            return result
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/scan")
    def scan(request: ScanRequest) -> dict[str, Any]:
        try:
            result = current_scanner_service().scan_many(
                request.symbols, period=request.period, interval=request.interval,
                capital=request.capital, top_n=request.top_n
            )
            if not isinstance(result, dict):
                raise ValueError("Scanner returned an invalid batch result contract")
            return result
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


app = create_app()
__all__ = ["app", "create_app", "get_application", "get_scanner_service"]
