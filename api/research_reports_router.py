"""Protected persistent research batches and automatically generated reports."""

import base64
import os
import re
import threading
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from api.admin_auth import require_admin_api_key
from config.nifty_universes import NIFTY_UNIVERSES
from config.scanner_capacity import MAX_BACKTEST_SYMBOLS
from core.deployment_role import on_render
from core.storage_config import storage_health
from services.cloud_workload_gate import CloudWorkloadBusy
from services.research_batches import ResearchBatchManager, ResearchQueueFull


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str] = Field(min_length=1, max_length=MAX_BACKTEST_SYMBOLS)
    strategy_id: str = Field(min_length=1, max_length=80)
    horizon: Literal[
        "intraday", "short_swing", "short_term", "medium_term", "long_term"
    ]
    stock_list: str = Field(max_length=80)
    short_borrow_available: StrictBool = False
    period: Literal["30d", "45d", "60d", "1y", "2y", "5y"] | None = None
    strategy_ids: list[str] | None = Field(default=None, min_length=1, max_length=19)

    @field_validator("stock_list")
    @classmethod
    def official_list(cls, value):
        if value not in NIFTY_UNIVERSES:
            raise ValueError("Choose an official stock list")
        return value


def research_reports_router(
    app, technical_getter, *, manager_factory=ResearchBatchManager
):
    router = APIRouter(prefix="/reports", dependencies=[Depends(require_admin_api_key)])
    control = threading.Lock()

    def manager():
        with control:
            if not hasattr(app.state, "research_batches"):
                if str(os.getenv("WEB_CONCURRENCY", "1")) != "1":
                    raise HTTPException(
                        503, "Research reports require one application worker"
                    )
                try:
                    app.state.research_batches = manager_factory(technical_getter())
                except Exception:
                    raise HTTPException(503, "Report storage is unavailable") from None
            return app.state.research_batches

    @router.post("/{kind}", status_code=202)
    def submit(kind: Literal["scan", "backtest"], request: ResearchRequest):
        try:
            batch = manager().submit(kind, request.model_dump())
            return {
                **{
                    key: batch[key]
                    for key in ("batch_id", "kind", "status", "created_at")
                },
                "partition_count": len(batch["request"].get("partitions") or [None]),
            }
        except ResearchQueueFull as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "10"}) from None
        except CloudWorkloadBusy as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Research batch could not be started") from None

    @router.get("/batches")
    def batches(
        kind: Literal["scan", "backtest"] | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        return {"batches": manager().repository.latest(kind, limit, offset)}

    @router.post("/batches/{batch_id}/cancel")
    def cancel_batch(batch_id: str):
        try:
            return manager().cancel(batch_id)
        except ValueError:
            raise HTTPException(404, "Research batch not found") from None

    @router.get("/storage")
    def report_storage():
        worker = manager()
        return {
            "runtime": "render" if on_render() else "local",
            "mode": (
                "persistent_cloud"
                if on_render() and worker.archive is not None
                else "pc_files"
                if worker.archive is not None
                else "temporary_cloud"
            ),
            "archive_path": str(worker.archive.root)
            if worker.archive is not None
            else None,
            "recovery": worker.archive_recovery,
            "seed_recovery": worker.seed_recovery,
            "storage_health": storage_health(),
            "execution": "isolated_process" if worker.isolated else "local_thread",
            "pc_sync_connected": False,
        }

    @router.get("/summary")
    def report_summary():
        repository = manager().repository
        return {
            "storage": report_storage(),
            "latest_completed": {
                kind: next(iter(repository.latest(kind, 1, completed_only=True)), None)
                for kind in ("scan", "backtest")
            },
        }

    def detail(batch_id):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", batch_id):
            raise HTTPException(404, "Research batch not found")
        batch = manager().repository.get(batch_id)
        if batch is None:
            raise HTTPException(404, "Research batch not found")
        return batch

    @router.get("/batches/{batch_id}")
    def batch_detail(batch_id: str):
        return detail(batch_id)

    @router.get("/batches/{batch_id}/report.csv")
    def report_csv(batch_id: str):
        batch = detail(batch_id)
        if batch["status"] != "completed" or not batch["report"]:
            raise HTTPException(
                409, "Report is available only after the batch completes"
            )
        return Response(
            batch["report"]["csv"].encode("utf-8-sig"),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{batch_id}.csv"'},
        )

    @router.get("/batches/{batch_id}/report.xlsx")
    def report_excel(batch_id: str):
        batch = detail(batch_id)
        report = batch["report"]
        if (
            batch["status"] != "completed"
            or not report
            or not report.get("xlsx_base64")
        ):
            raise HTTPException(409, "Excel report is unavailable for this batch")
        return Response(
            base64.b64decode(report["xlsx_base64"], validate=True),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{batch_id}.xlsx"'},
        )

    return router
