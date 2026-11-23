"""Authenticated scanner journal, research queue and encrypted evidence routes."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response

from api.admin_auth import require_admin_api_key
from services.scanner_workflow import ScannerBacktestDispatcher
from services.scanner_workflow_export import (
    backtest_view,
    export_job,
    export_pending_queue,
)


def scanner_workflow_router(manager_getter):
    router = APIRouter(dependencies=[Depends(require_admin_api_key)])

    def dispatcher():
        manager = manager_getter()
        with manager._control:
            if not getattr(manager, "scanner_dispatcher", None):
                manager.scanner_dispatcher = ScannerBacktestDispatcher(manager)
            return manager.scanner_dispatcher

    @router.get("/scanner-runs")
    def reports():
        return {
            "runs": dispatcher().workflow.reports(),
            "retention": {"completed_scanner_runs": 10},
        }

    @router.get("/scanner-runs/{run_id}")
    def report(run_id: str):
        try:
            return JSONResponse(dispatcher().workflow.report(run_id))
        except KeyError:
            raise HTTPException(
                404, "Scanner report is outside retention or unavailable"
            ) from None

    @router.get("/backtest-queue")
    def queue():
        worker = dispatcher()
        worker.workflow.reconcile()
        return backtest_view(worker.workflow)

    @router.post("/backtest-queue/start")
    def start():
        return dispatcher().start()

    @router.get("/backtest-queue/queued-stocks.xlsx")
    def queued_excel():
        try:
            content = export_pending_queue(dispatcher().workflow)
        except ValueError:
            raise HTTPException(
                409, "Configure the TrendForge export password before downloading Excel"
            ) from None
        return Response(
            content,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": (
                    'attachment; filename="trendforge-queued-stock-strategies.xlsx"'
                ),
                "Cache-Control": "private, no-store",
            },
        )

    @router.get("/backtest-queue/{job_id}/trades.xlsx")
    def excel(job_id: str):
        try:
            content = export_job(dispatcher().workflow, job_id)
        except ValueError as exc:
            # All validation text is fixed locally; no provider body is copied.
            raise HTTPException(
                409,
                (
                    "Encrypted trade evidence is unavailable until this backtest "
                    "completes and its export password is "
                    "configured"
                ),
            ) from exc
        return Response(
            content,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": (
                    'attachment; filename="trendforge-backtest-trades.xlsx"'
                ),
                "Cache-Control": "private, no-store",
            },
        )

    return router
