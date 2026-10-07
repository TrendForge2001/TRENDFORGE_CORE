"""Canonical FastAPI application boundary for TrendForge Core."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
from typing import Any, Callable

from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.application_factory import ApplicationFactory, build_application_factory
from core.database import initialize_database


MAX_FUNDAMENTAL_UPLOAD_BYTES = 10 * 1024 * 1024


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


class FundamentalUpdateRequest(BaseModel):
    """Partial manual update; omitted values preserve existing SQLite fields."""

    model_config = ConfigDict(extra="forbid")

    roce: float | None = Field(default=None, ge=-1000, le=1000)
    roe: float | None = Field(default=None, ge=-1000, le=1000)
    sales_growth: float | None = Field(default=None, ge=-1000, le=1000)
    profit_growth: float | None = Field(default=None, ge=-1000, le=1000)
    eps_growth: float | None = Field(default=None, ge=-1000, le=1000)
    debt_equity: float | None = Field(default=None, ge=0)
    promoter_holding: float | None = Field(default=None, ge=0, le=100)
    pledged: float | None = Field(default=None, ge=0, le=100)
    source: str = Field(default="manual", min_length=1, max_length=100)
    as_of: str | None = None


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

    def current_fundamental_manager():
        return current_application().fundamental_manager()

    def current_fundamental_completion_service():
        return current_application().fundamental_completion_service()

    initializer = database_initializer or initialize_database

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _app.state.database = initializer()
        importer = getattr(
            current_application(),
            "import_fundamentals_if_configured",
            None,
        )
        _app.state.fundamentals_import = (
            importer()
            if callable(importer)
            else {"status": "not_supported"}
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

    @app.get("/fundamentals/template.csv")
    def fundamentals_template_csv() -> Response:
        try:
            content = current_fundamental_manager().template_csv()
            return Response(
                content=content,
                media_type="text/csv",
                headers={
                    "Content-Disposition":
                    'attachment; filename="trendforge_fundamentals_template.csv"'
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/fundamentals/template.xlsx")
    def fundamentals_template_xlsx() -> Response:
        try:
            content = current_fundamental_manager().template_xlsx()
            return Response(
                content=content,
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                headers={
                    "Content-Disposition":
                    'attachment; filename="trendforge_fundamentals_template.xlsx"'
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/fundamentals/upload")
    async def upload_fundamentals(
        file: UploadFile = File(...),
        source: str = Form(default="manual_upload"),
        symbol_column: str | None = Form(default=None),
        field_map: str | None = Form(default=None),
        sheet: str = Form(default="0"),
        as_of: str | None = Form(default=None),
    ) -> dict[str, Any]:
        filename = Path(file.filename or "").name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xlsm"}:
            raise HTTPException(
                status_code=422,
                detail="Fundamentals upload must be CSV, XLSX or XLSM",
            )

        payload = await file.read(MAX_FUNDAMENTAL_UPLOAD_BYTES + 1)
        if len(payload) > MAX_FUNDAMENTAL_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Fundamentals upload exceeds 10 MB",
            )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=suffix,
                delete=False,
            ) as handle:
                handle.write(payload)
                temporary_path = Path(handle.name)

            return current_fundamental_manager().import_file(
                temporary_path,
                source=source,
                symbol_column=symbol_column,
                field_map=field_map,
                sheet_name=sheet,
                as_of=as_of,
                source_file_name=filename,
            )
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @app.get("/fundamentals/completion.csv")
    def fundamentals_completion_csv() -> Response:
        try:
            content = current_fundamental_completion_service().completion_csv()
            return Response(
                content=content,
                media_type="text/csv",
                headers={
                    "Content-Disposition":
                    'attachment; filename="trendforge_fundamental_completion.csv"'
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/fundamentals/completion.xlsx")
    def fundamentals_completion_xlsx() -> Response:
        try:
            content = current_fundamental_completion_service().completion_xlsx()
            return Response(
                content=content,
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                headers={
                    "Content-Disposition":
                    'attachment; filename="trendforge_fundamental_completion.xlsx"'
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/fundamentals/completion/upload")
    async def upload_fundamental_completion(
        file: UploadFile = File(...),
        apply: bool = Form(default=False),
        source: str | None = Form(default=None),
        as_of: str | None = Form(default=None),
        sheet: str = Form(default="Completion"),
    ) -> dict[str, Any]:
        filename = Path(file.filename or "").name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xlsm"}:
            raise HTTPException(
                status_code=422,
                detail="Completion upload must be CSV, XLSX or XLSM",
            )

        payload = await file.read(MAX_FUNDAMENTAL_UPLOAD_BYTES + 1)
        if len(payload) > MAX_FUNDAMENTAL_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Completion upload exceeds 10 MB",
            )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=suffix,
                delete=False,
            ) as handle:
                handle.write(payload)
                temporary_path = Path(handle.name)

            return current_fundamental_completion_service().process_file(
                temporary_path,
                apply=apply,
                source=source,
                as_of=as_of,
                sheet_name=sheet,
                source_file_name=filename,
            )
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @app.get("/fundamentals/{symbol}/evidence")
    def fundamental_completion_evidence(
        symbol: str,
        limit: int = Query(default=500, ge=1, le=2000),
    ) -> dict[str, Any]:
        try:
            return current_fundamental_completion_service().evidence(
                symbol,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/fundamentals/{symbol}/history")
    def fundamental_completion_history(
        symbol: str,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        try:
            return {
                "symbol": symbol.strip().upper(),
                "history": current_fundamental_completion_service().history(
                    symbol,
                    limit=limit,
                ),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/fundamentals")
    def fundamentals_report(
        limit: int = Query(default=1000, ge=1, le=5000),
        incomplete_only: bool = False,
        stale_only: bool = False,
    ) -> dict[str, Any]:
        try:
            return current_fundamental_manager().report(
                limit=limit,
                incomplete_only=incomplete_only,
                stale_only=stale_only,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/fundamentals/{symbol}")
    def fundamental_by_symbol(symbol: str) -> dict[str, Any]:
        try:
            result = current_fundamental_manager().inspect(symbol)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="Fundamentals not found")
        return result

    @app.put("/fundamentals/{symbol}")
    def update_fundamental(
        symbol: str,
        request: FundamentalUpdateRequest,
    ) -> dict[str, Any]:
        values = request.model_dump(
            exclude={"source", "as_of"},
            exclude_none=True,
        )
        try:
            return current_fundamental_manager().upsert(
                symbol,
                values,
                source=request.source,
                as_of=request.as_of,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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
__all__ = [
    "app",
    "create_app",
    "get_application",
    "get_scanner_service",
    "FundamentalUpdateRequest",
]
