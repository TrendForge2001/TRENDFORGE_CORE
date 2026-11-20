"""Authenticated private workbook import and conditional stock selection."""

import json
import threading
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from api.big_shark_auth import require_big_shark_access
from core.storage_config import production_runtime_enabled, storage_health
from database.repositories.big_shark_repository import (
    BigSharkRepository,
    BigSharkSnapshotConflict,
)
from services.big_shark_activity import (
    activity_view,
    import_records,
    parse_csv,
    trade_template_bytes,
)
from services.big_shark_confirmation import refresh_confirmations
from services.big_shark_portfolio import (
    MAX_WORKBOOK_BYTES,
    bootstrap_from_environment,
    read_portfolio,
    workbook_bytes,
)


class TradeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    trade_date: str = Field(max_length=30)
    symbol: str = Field(max_length=25)
    investor_name: str = Field(min_length=1, max_length=300)
    side: str = Field(max_length=10)
    quantity: str | int | float
    price: str | int | float | None = None
    stock_name: str | None = Field(default=None, max_length=300)
    disclosed_at: str | None = Field(default=None, max_length=80)
    trade_id: str | None = Field(default=None, max_length=100)


class TradeFeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["NSE_BULK", "NSE_BLOCK", "OWNER_CSV"] = "OWNER_CSV"
    metric: Literal["quantity", "value"] = "quantity"
    records: list[TradeRecord] = Field(min_length=1, max_length=10000)
    investor_aliases: dict[str, str] = Field(default_factory=dict, max_length=1000)
    period_start: date | None = None
    period_end: date | None = None
    disclosed_at: str | None = Field(default=None, max_length=80)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    symbols: list[str] = Field(min_length=1, max_length=5)


class PublicRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    source: Literal["NSE_BULK", "NSE_BLOCK"] = "NSE_BULK"
    metric: Literal["quantity", "value"] = "quantity"
    period_start: date | None = None
    period_end: date | None = None
    investor_aliases: dict[str, str] = Field(default_factory=dict, max_length=1000)


class PublicFeedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    source: Literal["NSE_BULK", "NSE_BLOCK"] = "NSE_BULK"
    metric: Literal["quantity", "value"] = "quantity"
    investor_aliases: dict[str, str] = Field(default_factory=dict, max_length=1000)


def big_shark_router(technical_getter=None, *, public_provider_getter=None):
    router = APIRouter(
        prefix="/institutional/big-shark",
        dependencies=[Depends(require_big_shark_access)],
    )
    confirmation_lock = threading.Lock()

    def durable_write():
        if production_runtime_enabled() and not storage_health()["verified_persistent"]:
            raise HTTPException(
                503, "Private imports require verified persistent storage."
            )

    def repository():
        repo = BigSharkRepository()
        try:
            if (
                not production_runtime_enabled()
                or storage_health()["verified_persistent"]
            ):
                bootstrap_from_environment(repo)
            yield repo
        finally:
            repo.close()

    def latest(repo):
        snapshot = repo.latest()
        if not snapshot:
            raise HTTPException(404, "No private Big Shark workbook has been imported.")
        return snapshot

    @router.get("/sources")
    def public_sources(repo: Annotated[BigSharkRepository, Depends(repository)]):
        from services.big_shark_public_feed import source_view

        return JSONResponse(
            source_view(repo), headers={"Cache-Control": "private, no-store"}
        )

    @router.post("/sources/refresh")
    def refresh_sources(
        request: PublicRefreshRequest,
        repo: Annotated[BigSharkRepository, Depends(repository)],
    ):
        durable_write()
        from providers.big_shark_public import PublicFeedError
        from services.big_shark_public_feed import refresh_public_sources

        try:
            result = refresh_public_sources(
                repo,
                provider=public_provider_getter() if public_provider_getter else None,
                source=request.source,
                metric=request.metric,
                start=request.period_start,
                end=request.period_end,
                aliases=request.investor_aliases,
                expected_snapshot_id=request.snapshot_id,
            )
            return JSONResponse(result, headers={"Cache-Control": "private, no-store"})
        except BigSharkSnapshotConflict:
            raise HTTPException(
                409, "Portfolio changed during refresh; reload and retry."
            ) from None
        except PublicFeedError:
            raise HTTPException(
                409, "Another public-source refresh is running."
            ) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.put("/sources/config")
    def configure_sources(
        request: PublicFeedConfig,
        repo: Annotated[BigSharkRepository, Depends(repository)],
    ):
        durable_write()
        from services.big_shark_public_feed import _tracked, source_view

        if request.investor_aliases:
            try:
                _tracked(latest(repo), request.investor_aliases)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
        repo.save_source_state(
            {
                "enabled": request.enabled,
                "source": request.source,
                "metric": request.metric,
                "aliases": request.investor_aliases,
                "refresh_interval_hours": 24,
            },
            "config",
        )
        return JSONResponse(
            source_view(repo), headers={"Cache-Control": "private, no-store"}
        )

    @router.get("", response_class=Response)
    def get_snapshot(repo: Annotated[BigSharkRepository, Depends(repository)]):
        return Response(
            json.dumps(activity_view(latest(repo)), allow_nan=False),
            media_type="application/json",
            headers={"Cache-Control": "private, no-store"},
        )

    @router.post("/import")
    async def import_workbook(
        file: Annotated[UploadFile, File()],
        repo: Annotated[BigSharkRepository, Depends(repository)],
        symbol_map: str = Form("{}"),
        reporting_period: str = Form(""),
        metric: str = Form("quantity"),
    ):
        durable_write()
        data = await file.read(MAX_WORKBOOK_BYTES + 1)
        await file.close()
        try:
            mapping = json.loads(symbol_map)
            import re

            if (
                not isinstance(mapping, dict)
                or len(mapping) > 10000
                or any(
                    not isinstance(k, str)
                    or not isinstance(v, str)
                    or not re.fullmatch(r"[A-Z0-9][A-Z0-9&.\-]{0,24}", v)
                    for k, v in mapping.items()
                )
            ):
                raise ValueError(
                    "Symbol mapping must map stock names to exact NSE symbols."
                )
            snapshot = read_portfolio(
                data,
                symbol_map=mapping,
                reporting_period=reporting_period.strip() or None,
                metric=metric,
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None
        return repo.save(snapshot)

    def save_feed(repo, records, **options):
        durable_write()
        original = latest(repo)
        try:
            updated = import_records(original, records, **options)
            return repo.save(updated, expected_snapshot_id=original["snapshot_id"])
        except BigSharkSnapshotConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get("/trades/template")
    def trade_template():
        return Response(
            trade_template_bytes(),
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    'attachment; filename="Big_Shark_Trades_Template.csv"'
                ),
                "Cache-Control": "private, no-store",
            },
        )

    @router.post("/trades/import")
    async def import_trade_csv(
        file: Annotated[UploadFile, File()],
        repo: Annotated[BigSharkRepository, Depends(repository)],
        source: str = Form("NSE_BULK"),
        metric: str = Form("quantity"),
        investor_aliases: str = Form("{}"),
        period_start: str = Form(""),
        period_end: str = Form(""),
        disclosed_at: str = Form(""),
    ):
        durable_write()
        data = await file.read(MAX_WORKBOOK_BYTES + 1)
        await file.close()
        try:
            aliases = json.loads(investor_aliases)
            if not isinstance(aliases, dict) or len(aliases) > 1000:
                raise ValueError("Supply a JSON object of verified investor aliases.")
            records = parse_csv(data)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None
        return save_feed(
            repo,
            records,
            source=source,
            metric=metric,
            aliases=aliases,
            period_start=period_start or None,
            period_end=period_end or None,
            default_disclosed_at=disclosed_at or None,
        )

    @router.post("/trades/feed")
    def accept_trade_feed(
        request: TradeFeed, repo: Annotated[BigSharkRepository, Depends(repository)]
    ):
        saved = save_feed(
            repo,
            [r.model_dump() for r in request.records],
            source=request.source,
            metric=request.metric,
            aliases=request.investor_aliases,
            period_start=request.period_start,
            period_end=request.period_end,
            default_disclosed_at=request.disclosed_at,
        )
        # A scoped provider credential must never receive private holdings.
        return JSONResponse(
            {
                "status": "accepted",
                "snapshot_id": saved["snapshot_id"],
                "records_received": len(request.records),
                "execution_enabled": False,
            },
            headers={"Cache-Control": "private, no-store"},
        )

    @router.post("/confirm")
    def confirm_daily(
        request: ConfirmRequest,
        repo: Annotated[BigSharkRepository, Depends(repository)],
    ):
        durable_write()
        original = latest(repo)
        if original["snapshot_id"] != request.snapshot_id:
            raise HTTPException(409, "Portfolio changed; reload before checking.")
        if technical_getter is None:
            raise HTTPException(503, "Daily Kite confirmation is not configured.")
        if not confirmation_lock.acquire(blocking=False):
            raise HTTPException(409, "Another daily confirmation is already running.")
        try:
            from core.deployment_role import on_render
            from services.cloud_workload_gate import paper_busy, research_busy

            if on_render() and (paper_busy() or research_busy()):
                raise HTTPException(
                    409, "Finish active paper automation or research before checking."
                )
            try:
                technical = technical_getter()
                market_data = technical.market_data
            except Exception:
                raise HTTPException(
                    503, "Daily Kite candles are unavailable."
                ) from None
            updated = refresh_confirmations(original, market_data, request.symbols)
            return repo.save(updated, expected_snapshot_id=request.snapshot_id)
        except BigSharkSnapshotConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        finally:
            confirmation_lock.release()

    @router.get("/workbook")
    def export_workbook(repo: Annotated[BigSharkRepository, Depends(repository)]):
        return Response(
            workbook_bytes(latest(repo), public_sources=repo.source_state()),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": (
                    'attachment; filename="Big_Shark_Recalculated.xlsx"'
                ),
                "Cache-Control": "private, no-store",
            },
        )

    return router
