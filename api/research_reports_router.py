"""Protected persistent research batches and automatically generated reports."""

import base64
import os
import re
import threading
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from starlette.responses import JSONResponse

from api.admin_auth import require_admin_api_key
from config.scanner_capacity import MAX_BACKTEST_SYMBOLS
from config.stock_lists import EQUITY_STOCK_LISTS
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
    cost_bps: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    slippage_bps: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    initial_capital: float | None = Field(
        default=None, ge=1000, le=1_000_000_000, allow_inf_nan=False
    )
    risk_fraction: float | None = Field(
        default=None, gt=0, le=0.02, allow_inf_nan=False
    )
    max_positions: int | None = Field(default=None, ge=1, le=3, strict=True)
    move_stop_after_partial: StrictBool | None = None

    @field_validator("stock_list")
    @classmethod
    def official_list(cls, value):
        if value not in EQUITY_STOCK_LISTS:
            raise ValueError("Choose a constituent stock list for research")
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

    app.state.research_manager_getter = manager

    @router.post("/{kind}", status_code=202)
    def submit(kind: Literal["scan", "backtest"], request: ResearchRequest):
        payload = request.model_dump(exclude_none=True)
        overrides = {
            "initial_capital",
            "risk_fraction",
            "max_positions",
            "move_stop_after_partial",
        }
        if kind == "scan" and payload.keys() & (
            overrides | {"cost_bps", "slippage_bps"}
        ):
            raise HTTPException(422, "Backtest parameters require a backtest")
        if payload.keys() & overrides:
            from scanner.approved_strategies import active

            if not all(
                active(key) for key in (request.strategy_ids or [request.strategy_id])
            ):
                raise HTTPException(
                    422, "Account overrides require an approved horizon strategy"
                )
            if request.move_stop_after_partial is not None and request.horizon not in {
                "medium_term",
                "long_term",
            }:
                raise HTTPException(
                    422,
                    "Moving the stop requires a strategy that books partial profits",
                )
        try:
            batch = manager().submit(kind, payload)
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
        stock_list: str | None = Query(default=None, max_length=80),
        completed_only: bool = False,
        primary_only: bool = False,
    ):
        return {
            "batches": manager().repository.latest(
                kind,
                limit,
                offset,
                stock_list=stock_list,
                completed_only=completed_only,
                primary_only=primary_only,
            )
        }

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
                kind: next(
                    iter(
                        repository.latest(
                            kind, 1, completed_only=True, primary_only=kind == "scan"
                        )
                    ),
                    None,
                )
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

    @router.post("/batches/{batch_id}/retry-errors", status_code=202)
    def retry_scan_errors(batch_id: str):
        from services.scan_recheck import retry_request

        source = detail(batch_id)
        worker = manager()
        try:
            batch = worker.submit("scan", retry_request(worker.repository, source))
        except ResearchQueueFull as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "10"}) from None
        except CloudWorkloadBusy as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {key: batch[key] for key in ("batch_id", "status", "requested_symbols")}

    @router.get("/batches/{batch_id}")
    def batch_detail(batch_id: str):
        # Persisted batches already contain JSON-native values. Avoid FastAPI's
        # recursive Python encoder for multi-megabyte campaign reports; render
        # the response in this sync endpoint's thread, keeping /livez responsive.
        return JSONResponse(detail(batch_id))

    @router.get("/batches/{batch_id}/workbench")
    def batch_workbench(batch_id: str, metadata_only: bool = False):
        batch = detail(batch_id)
        if not metadata_only and batch["kind"] == "scan":
            from services.scan_recheck import failed_symbols, latest_recheck

            batch["scan_recheck_available"] = bool(failed_symbols(batch))
            if batch["scan_recheck_available"]:
                batch["scan_recheck"] = latest_recheck(manager().repository, batch)
        if batch["report"]:
            excluded = {
                "csv",
                "xlsx_base64",
                "comparison_results",
                "allocations",
                "rejected_entries",
            }
            if metadata_only:
                excluded.update({"rows", "equity_curve", "benchmark"})
            elif (
                batch["kind"] == "backtest"
                and batch["report"].get("report_type")
                == "historical_backtest_exit_fills"
                and not batch["report"].get("equity_curve")
            ):
                technical = technical_getter()
                saved = (
                    technical.repository.by_run_id(batch["batch_id"])
                    if technical
                    else None
                )
                result = (saved or {}).get("result", {})
                batch["report"].update(
                    equity_curve=[
                        {"date": point["date"], "equity": point["equity"]}
                        for point in result.get("equity_curve", [])
                    ],
                    trade_interval=result.get("interval"),
                )
            batch["report"] = {
                key: value
                for key, value in batch["report"].items()
                if key not in excluded
            }
        return JSONResponse(batch)

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

    @router.get("/batches/{batch_id}/consolidated.xlsx")
    def report_consolidated_excel(batch_id: str):
        from core.report_access import encrypted_excel
        from services.workbench_export import consolidated_workbook

        batch = detail(batch_id)
        report = batch.get("report") or {}
        if batch["kind"] != "backtest" or batch["status"] != "completed":
            raise HTTPException(
                409, "The backtest must complete before it can be exported"
            )
        accounts = [batch]
        if report.get("report_type") == "research_partition_manifest":
            accounts = [detail(row["batch_id"]) for row in report.get("rows", [])]
        if not accounts or any(
            account["kind"] != "backtest"
            or account["status"] != "completed"
            or (account.get("report") or {}).get("report_type")
            != "historical_backtest_exit_fills"
            for account in accounts
        ):
            raise HTTPException(
                409, "Completed trade evidence is unavailable for this run"
            )
        try:
            content = encrypted_excel(consolidated_workbook(batch, accounts))
        except ValueError:
            raise HTTPException(409, "Excel report is unavailable") from None
        filename = f"{batch_id}-consolidated.xlsx"
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/batches/{batch_id}/report.xlsx")
    def report_excel(batch_id: str):
        from core.report_access import encrypted_excel

        batch = detail(batch_id)
        report = batch["report"]
        if (
            batch["status"] != "completed"
            or not report
            or not report.get("xlsx_base64")
        ):
            raise HTTPException(409, "Excel report is unavailable for this batch")
        try:
            content = encrypted_excel(
                base64.b64decode(report["xlsx_base64"], validate=True)
            )
        except ValueError:
            raise HTTPException(
                409,
                ("Configure the TrendForge export password before downloading Excel"),
            ) from None
        return Response(
            content,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={"Content-Disposition": f'attachment; filename="{batch_id}.xlsx"'},
        )

    from api.scanner_workflow_router import scanner_workflow_router

    router.include_router(scanner_workflow_router(manager))
    return router
