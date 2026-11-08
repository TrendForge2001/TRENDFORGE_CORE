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

    @field_validator("stock_list")
    @classmethod
    def official_list(cls, value):
        if value not in NIFTY_UNIVERSES:
            raise ValueError("Choose an official stock list")
        return value


def research_reports_router(app, technical_getter):
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
                    app.state.research_batches = ResearchBatchManager(
                        technical_getter()
                    )
                except Exception:
                    raise HTTPException(503, "Report storage is unavailable") from None
            return app.state.research_batches

    @router.post("/{kind}", status_code=202)
    def submit(kind: Literal["scan", "backtest"], request: ResearchRequest):
        try:
            batch = manager().submit(kind, request.model_dump())
            return {
                key: batch[key] for key in ("batch_id", "kind", "status", "created_at")
            }
        except ResearchQueueFull as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "10"}) from None
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

    @router.get("/storage")
    def report_storage():
        worker = manager()
        return {
            "mode": "pc_files" if worker.archive is not None else "temporary_cloud",
            "archive_path": str(worker.archive.root)
            if worker.archive is not None
            else None,
            "recovery": worker.archive_recovery,
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
