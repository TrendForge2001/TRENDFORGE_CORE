"""Canonical FastAPI application boundary for TrendForge Core."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import time
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.production_runtime import production_runtime_enabled, secure_application

from core.application_factory import ApplicationFactory, build_application_factory
from core.database import initialize_database
from database.repositories.scan_run_audit_repository import (
    DuplicateScanRunIdError,
)
from services.scan_execution_guard import ScanExecutionGuard


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


class Nifty500ScanRequest(BaseModel):
    period: str = "6mo"
    interval: str = "1d"
    capital: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    top_n: int = Field(default=20, ge=1, le=500)
    batch_size: int = Field(default=25, ge=1, le=100)
    batch_pause_seconds: float = Field(default=1.0, ge=0, le=10)
    scan_time_budget_seconds: float = Field(
        default=450.0,
        ge=10.0,
        le=900.0,
    )
    batch_time_budget_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=180.0,
    )
    limit: int = Field(default=25, ge=1, le=500)
    full_universe: bool = False
    refresh_universe: bool = False
    compact: bool = True


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

    def current_nifty500_universe():
        application = current_application()
        method = getattr(application, "nifty500_universe", None)
        if not callable(method):
            raise RuntimeError(
                "NIFTY 500 universe is not available in this application"
            )
        return method()

    def current_fundamental_manager():
        return current_application().fundamental_manager()

    def current_fundamental_completion_service():
        return current_application().fundamental_completion_service()

    def current_scan_run_audit_service():
        application = current_application()
        method = getattr(application, "scan_run_audit_service", None)
        return method() if callable(method) else None

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

    scan_execution_guard = ScanExecutionGuard()
    app.state.scan_execution_guard = scan_execution_guard

    @app.get("/")
    def root() -> dict[str, Any]:
        return {"service": "TrendForge Core", "status": "ok"}

    @app.get("/health")
    def health() -> dict[str, Any]:
        try:
            return current_application().health()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/observability/scan-runtime")
    def scan_runtime_status() -> dict[str, Any]:
        return scan_execution_guard.status()

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

    @app.get("/universe/nifty500")
    def nifty500_universe(
        refresh: bool = False,
        include_members: bool = False,
    ) -> dict[str, Any]:
        try:
            universe = current_nifty500_universe()
            universe.ensure_loaded(refresh=refresh)
            return universe.report(include_members=include_members)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/scan/universe/nifty500")
    def scan_nifty500(
        request: Nifty500ScanRequest,
        run_id: str | None = Query(default=None, max_length=128),
    ) -> dict[str, Any]:
        scan_run_id = str(run_id or uuid4()).strip()
        audit_service = current_scan_run_audit_service()

        if audit_service is not None:
            try:
                audit_service.ensure_available(scan_run_id)
            except DuplicateScanRunIdError as exc:
                existing = audit_service.get(scan_run_id)
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "scan run_id already exists",
                        "run_id": scan_run_id,
                        "existing_outcome": (
                            existing.get("outcome")
                            if isinstance(existing, dict)
                            else None
                        ),
                    },
                ) from exc

        if not scan_execution_guard.try_start(scan_run_id):
            state = scan_execution_guard.status()
            active = state.get("active")
            active_run_id = (
                active.get("run_id")
                if isinstance(active, dict)
                else None
            )
            now = datetime.now(timezone.utc)
            if (
                audit_service is not None
                and active_run_id != scan_run_id
            ):
                try:
                    audit_service.record(
                        {
                            "run_id": scan_run_id,
                            "scan_type": "nifty500",
                            "outcome": "rejected",
                            "http_status": 409,
                            "failure_stage": "admission",
                            "failure_message": (
                                "Another NIFTY 500 universe scan is "
                                "already running"
                            ),
                            "started_at": now.isoformat(),
                            "finished_at": now.isoformat(),
                            "duration_sec": 0.0,
                            "requested_symbols": (
                                500
                                if request.full_universe
                                else request.limit
                            ),
                            "completed_symbols": 0,
                            "error_symbols": 0,
                            "missing_symbols": 0,
                            "enrichment_failures": 0,
                            "execution_errors": 0,
                            "full_universe": request.full_universe,
                            "source_security_count": None,
                            "tradable_security_count": None,
                            "provider_counts": {},
                            "fallback_count": 0,
                            "nse_resolution_count": 0,
                            "error_details": {},
                            "metadata": {
                                "period": request.period,
                                "interval": request.interval,
                                "batch_size": request.batch_size,
                                "batch_pause_seconds": (
                                    request.batch_pause_seconds
                                ),
                                "active_run_id": (
                                    active.get("run_id")
                                    if isinstance(active, dict)
                                    else None
                                ),
                            },
                        }
                    )
                except DuplicateScanRunIdError:
                    pass

            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "Another NIFTY 500 universe scan is already running"
                    ),
                    "run_id": scan_run_id,
                    "active": active,
                    "duplicate_active_run_id": (
                        active_run_id == scan_run_id
                    ),
                },
                headers={"Retry-After": "15"},
            )

        started_at = datetime.now(timezone.utc)
        request_started = time.perf_counter()
        terminal_outcome = "failed"
        failure_stage = "universe_load"
        market_data = None
        members = []
        tradable_members = []
        placeholder_members = []
        symbols: list[str] = []
        scale_gate: dict[str, Any] = {}
        provider_observability: dict[str, Any] = {}

        scan_deadline_at = (
            started_at
            + timedelta(seconds=request.scan_time_budget_seconds)
        )
        scan_execution_guard.annotate(
            scan_run_id,
            limit=request.limit,
            full_universe=request.full_universe,
            batch_size=request.batch_size,
            period=request.period,
            interval=request.interval,
            scan_time_budget_seconds=request.scan_time_budget_seconds,
            batch_time_budget_seconds=request.batch_time_budget_seconds,
            deadline_at=scan_deadline_at.isoformat(),
            deadline_monotonic=(
                request_started + request.scan_time_budget_seconds
            ),
        )

        def audit_payload(
            *,
            outcome: str,
            http_status: int,
            failure_message: str | None = None,
        ) -> dict[str, Any]:
            finished_at = datetime.now(timezone.utc)
            requested_default = (
                len(symbols)
                if symbols
                else 500
                if request.full_universe
                else request.limit
            )
            return {
                "run_id": scan_run_id,
                "scan_type": "nifty500",
                "outcome": outcome,
                "http_status": http_status,
                "failure_stage": (
                    failure_stage
                    if outcome != "completed"
                    else None
                ),
                "failure_message": failure_message,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "duration_sec": float(
                    scale_gate.get(
                        "duration_sec",
                        time.perf_counter() - request_started,
                    )
                ),
                "requested_symbols": int(
                    scale_gate.get(
                        "requested_symbols",
                        requested_default,
                    )
                ),
                "completed_symbols": int(
                    scale_gate.get("completed_symbols", 0)
                ),
                "error_symbols": int(
                    scale_gate.get("error_symbols", 0)
                ),
                "missing_symbols": int(
                    scale_gate.get("missing_symbols", 0)
                ),
                "enrichment_failures": int(
                    scale_gate.get("enrichment_failures", 0)
                ),
                "execution_errors": int(
                    scale_gate.get("execution_errors", 0)
                ),
                "full_universe": bool(
                    scale_gate.get(
                        "full_universe",
                        request.full_universe,
                    )
                ),
                "source_security_count": (
                    scale_gate.get("source_security_count")
                    if scale_gate
                    else len(members) or None
                ),
                "tradable_security_count": (
                    scale_gate.get("tradable_security_count")
                    if scale_gate
                    else len(tradable_members) or None
                ),
                "provider_counts": dict(
                    provider_observability.get(
                        "provider_counts",
                        {},
                    )
                ),
                "fallback_count": int(
                    provider_observability.get(
                        "fallback_count",
                        0,
                    )
                    or 0
                ),
                "nse_resolution_count": int(
                    provider_observability.get(
                        "nse_resolution_count",
                        0,
                    )
                    or 0
                ),
                "error_details": (
                    dict(scale_gate.get("error_details") or {})
                    if scale_gate
                    else (
                        {"fatal": failure_message}
                        if failure_message
                        else {}
                    )
                ),
                "metadata": {
                    "period": request.period,
                    "interval": request.interval,
                    "batch_size": request.batch_size,
                    "batch_pause_seconds": (
                        request.batch_pause_seconds
                    ),
                    "scan_time_budget_seconds": (
                        request.scan_time_budget_seconds
                    ),
                    "batch_time_budget_seconds": (
                        request.batch_time_budget_seconds
                    ),
                    "time_budget_exhausted": bool(
                        scale_gate.get(
                            "time_budget_exhausted",
                            False,
                        )
                    ),
                    "time_budget_stop_reason": (
                        scale_gate.get(
                            "time_budget_stop_reason"
                        )
                    ),
                    "time_budget_stop_batch": (
                        scale_gate.get(
                            "time_budget_stop_batch"
                        )
                    ),
                    "processed_symbols": int(
                        scale_gate.get(
                            "processed_symbols",
                            0,
                        )
                        or 0
                    ),
                    "deferred_symbol_count": int(
                        scale_gate.get(
                            "deferred_symbol_count",
                            0,
                        )
                        or 0
                    ),
                    "progress_semantics_version": (
                        scale_gate.get(
                            "progress_semantics_version"
                        )
                    ),
                    "accounted_pct": scale_gate.get(
                        "accounted_pct"
                    ),
                    "processed_pct": scale_gate.get(
                        "processed_pct"
                    ),
                    "successful_pct": scale_gate.get(
                        "successful_pct"
                    ),
                    "error_pct": scale_gate.get("error_pct"),
                    "deferred_pct": scale_gate.get(
                        "deferred_pct"
                    ),
                    "missing_pct": scale_gate.get(
                        "missing_pct"
                    ),
                    "completion_pct_semantics": (
                        scale_gate.get(
                            "completion_pct_semantics"
                        )
                    ),
                    "scan_budget_headroom_sec": (
                        scale_gate.get(
                            "scan_budget_headroom_sec"
                        )
                    ),
                    "scan_budget_utilization_pct": (
                        scale_gate.get(
                            "scan_budget_utilization_pct"
                        )
                    ),
                    "scan_sla_met": scale_gate.get(
                        "scan_sla_met"
                    ),
                    "batch_sla_met": scale_gate.get(
                        "batch_sla_met"
                    ),
                    "sla_met": scale_gate.get("sla_met"),
                    "sla_status": scale_gate.get(
                        "sla_status"
                    ),
                    "max_batch_duration_sec": (
                        scale_gate.get(
                            "max_batch_duration_sec"
                        )
                    ),
                    "avg_batch_duration_sec": (
                        scale_gate.get(
                            "avg_batch_duration_sec"
                        )
                    ),
                    "batch_budget_breach_count": int(
                        scale_gate.get(
                            "batch_budget_breach_count",
                            0,
                        )
                        or 0
                    ),
                    "peak_batch_budget_utilization_pct": (
                        scale_gate.get(
                            "peak_batch_budget_utilization_pct"
                        )
                    ),
                    "excluded_index_placeholders": [
                        getattr(member, "symbol", None)
                        for member in placeholder_members
                        if getattr(member, "symbol", None)
                    ],
                    "circuit_skip_count": int(
                        provider_observability.get(
                            "circuit_skip_count",
                            0,
                        )
                        or 0
                    ),
                    "nse_resolver_attempts": int(
                        provider_observability.get(
                            "nse_resolver_attempts",
                            0,
                        )
                        or 0
                    ),
                    "nse_resolver_skips": int(
                        provider_observability.get(
                            "nse_resolver_skips",
                            0,
                        )
                        or 0
                    ),
                    "circuit_breakers": dict(
                        provider_observability.get(
                            "circuit_breakers",
                            {},
                        )
                    ),
                    "circuit_events": list(
                        provider_observability.get(
                            "circuit_events",
                            [],
                        )
                    ),
                },
            }

        try:
            universe = current_nifty500_universe()
            members = universe.ensure_loaded(
                refresh=request.refresh_universe
            )
            failure_stage = "universe_validation"
            report = universe.report(include_members=False)
            if str(report.get("status", "")).lower() != "healthy":
                raise RuntimeError(
                    "NIFTY 500 universe is not healthy: "
                    f"{report}"
                )
            if report.get("source") != "NSE_NIFTY500_CSV":
                raise RuntimeError(
                    "NIFTY 500 production scan requires canonical "
                    "NSE_NIFTY500_CSV source"
                )

            def is_index_placeholder(member) -> bool:
                symbol = str(
                    getattr(member, "symbol", "") or ""
                ).strip().upper()
                name = str(
                    getattr(member, "name", "") or ""
                ).strip().upper()
                return (
                    symbol.startswith("DUMMY")
                    or name.startswith("DUMMY ")
                )

            placeholder_members = [
                member for member in members
                if is_index_placeholder(member)
            ]
            tradable_members = [
                member for member in members
                if not is_index_placeholder(member)
            ]

            if request.full_universe:
                selected_members = list(tradable_members)
            else:
                if request.limit > len(tradable_members):
                    raise ValueError(
                        "Requested NIFTY 500 scan limit exceeds "
                        "tradable constituent security count "
                        f"{len(tradable_members)}"
                    )
                selected_members = list(
                    tradable_members[: request.limit]
                )

            symbols = [member.symbol for member in selected_members]
            failure_stage = "market_data_setup"

            market_aliases = {
                member.symbol: (
                    f"{member.symbol}"
                    f"{str(getattr(member, 'series', '') or '').strip().upper()}"
                )
                for member in selected_members
                if str(
                    getattr(member, "series", "") or ""
                ).strip().upper() == "RR"
            }
            application = current_application()
            market_data_factory = getattr(application, "market_data", None)
            if callable(market_data_factory):
                market_data = market_data_factory()
                alias_setter = getattr(
                    market_data,
                    "set_symbol_aliases",
                    None,
                )
                if callable(alias_setter):
                    alias_setter(market_aliases)
                begin_observation = getattr(
                    market_data,
                    "begin_observation",
                    None,
                )
                if callable(begin_observation):
                    begin_observation()

            failure_stage = "scan_execution"
            result = current_scanner_service().scan_universe(
                symbols,
                period=request.period,
                interval=request.interval,
                capital=request.capital,
                top_n=request.top_n,
                batch_size=request.batch_size,
                batch_pause_seconds=request.batch_pause_seconds,
                scan_time_budget_seconds=(
                    request.scan_time_budget_seconds
                ),
                batch_time_budget_seconds=(
                    request.batch_time_budget_seconds
                ),
            )
            if not isinstance(result, dict):
                raise ValueError(
                    "Scanner returned an invalid universe result contract"
                )

            result["universe"] = report
            raw_scale_gate = result.get("scale_gate")
            if isinstance(raw_scale_gate, dict):
                scale_gate = raw_scale_gate
                scale_gate["stage_limit"] = len(symbols)
                scale_gate["full_universe"] = (
                    len(symbols) == len(tradable_members)
                )
                scale_gate["source_security_count"] = len(members)
                scale_gate["tradable_security_count"] = len(
                    tradable_members
                )
                scale_gate["excluded_index_placeholders"] = [
                    member.symbol
                    for member in placeholder_members
                ]
                scale_gate["excluded_index_placeholder_count"] = len(
                    placeholder_members
                )
                scale_gate["nominal_company_count"] = int(
                    report.get("nominal_company_count", 500)
                )

            if market_data is not None:
                snapshot = getattr(
                    market_data,
                    "observability_snapshot",
                    None,
                )
                if callable(snapshot):
                    payload = snapshot(symbols)
                    if isinstance(payload, dict):
                        provider_observability = payload

            result["run_id"] = scan_run_id
            result["provider_observability"] = provider_observability
            if scale_gate:
                scale_gate["run_id"] = scan_run_id
                scale_gate["provider_counts"] = dict(
                    provider_observability.get(
                        "provider_counts",
                        {},
                    )
                )
                scale_gate["fallback_count"] = int(
                    provider_observability.get(
                        "fallback_count",
                        0,
                    )
                    or 0
                )
                scale_gate["nse_resolution_count"] = int(
                    provider_observability.get(
                        "nse_resolution_count",
                        0,
                    )
                    or 0
                )
                scale_gate["circuit_skip_count"] = int(
                    provider_observability.get(
                        "circuit_skip_count",
                        0,
                    )
                    or 0
                )
                scale_gate["nse_resolver_attempts"] = int(
                    provider_observability.get(
                        "nse_resolver_attempts",
                        0,
                    )
                    or 0
                )
                scale_gate["nse_resolver_skips"] = int(
                    provider_observability.get(
                        "nse_resolver_skips",
                        0,
                    )
                    or 0
                )
                scale_gate["circuit_breakers"] = dict(
                    provider_observability.get(
                        "circuit_breakers",
                        {},
                    )
                )

            is_partial = bool(
                scale_gate.get("time_budget_exhausted", False)
            )
            response_outcome = (
                "partial"
                if is_partial
                else "completed"
            )
            result["outcome"] = response_outcome
            if scale_gate:
                scale_gate["outcome"] = response_outcome

            if is_partial:
                failure_stage = "time_budget"
                failure_message = str(
                    scale_gate.get(
                        "time_budget_stop_reason"
                    )
                    or "scan time budget exhausted"
                )
            else:
                failure_stage = "audit_write"
                failure_message = None

            if audit_service is not None:
                audit_service.record(
                    audit_payload(
                        outcome=response_outcome,
                        http_status=200,
                        failure_message=failure_message,
                    )
                )

            if request.compact:
                items = list(result.get("results") or [])
                items.extend(list(result.get("rejected") or []))

                summaries = []
                for item in items:
                    signal = item.get("signal")
                    if isinstance(signal, dict):
                        signal = signal.get(
                            "signal",
                            signal.get("name", "HOLD"),
                        )
                    else:
                        signal = getattr(
                            signal,
                            "signal",
                            signal,
                        )
                    summaries.append(
                        {
                            "symbol": item.get("symbol"),
                            "signal": str(signal or "HOLD").upper(),
                            "eligible": bool(
                                item.get("eligible", False)
                            ),
                            "ranking_score": item.get(
                                "ranking_score",
                                0.0,
                            ),
                            "rejection_reason": item.get(
                                "rejection_reason"
                            ),
                            "error": item.get("error"),
                            "enrichment_failures": len(
                                item.get("enrichment_failures") or []
                            ),
                            "execution_errors": len(
                                item.get("execution_errors") or []
                            ),
                        }
                    )

                result["symbol_results"] = sorted(
                    summaries,
                    key=lambda row: str(row.get("symbol") or ""),
                )
                result.pop("results", None)
                result.pop("eligible", None)
                result.pop("rejected", None)

            terminal_outcome = response_outcome
            return result

        except DuplicateScanRunIdError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "scan run_id already exists",
                    "run_id": scan_run_id,
                },
            ) from exc
        except ValueError as exc:
            if audit_service is not None:
                try:
                    audit_service.record(
                        audit_payload(
                            outcome="failed",
                            http_status=422,
                            failure_message=str(exc),
                        )
                    )
                except DuplicateScanRunIdError:
                    pass
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            if audit_service is not None:
                try:
                    audit_service.record(
                        audit_payload(
                            outcome="failed",
                            http_status=503,
                            failure_message=str(exc),
                        )
                    )
                except DuplicateScanRunIdError:
                    pass
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            scan_execution_guard.finish(
                scan_run_id,
                terminal_outcome,
            )

    @app.get("/observability/scan-runs")
    def scan_run_audits(
        limit: int = Query(default=20, ge=1, le=500),
    ) -> dict[str, Any]:
        service = current_scan_run_audit_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Scan-run audit service is unavailable",
            )
        return {
            "runs": service.latest(limit),
            "limit": limit,
        }

    @app.get("/observability/scan-runs/{run_id}")
    def scan_run_audit(run_id: str) -> dict[str, Any]:
        service = current_scan_run_audit_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Scan-run audit service is unavailable",
            )
        record = service.get(run_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail="Scan run not found",
            )
        return record

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
if production_runtime_enabled():
    secure_application(app)
__all__ = [
    "app",
    "create_app",
    "get_application",
    "get_scanner_service",
    "FundamentalUpdateRequest",
    "Nifty500ScanRequest",
]
