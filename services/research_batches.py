"""Bounded background research; no order execution or automatic restart replay."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from database.repositories.research_batches import ResearchBatchRepository
from scanner.strategy_horizons import horizon_strategy
from services.execution_report import ReportValidationError
from services.portfolio_backtest_service import PortfolioBacktestService
from services.research_report import build_report

LOG = logging.getLogger(__name__)


class ResearchQueueFull(ValueError):
    pass


class ResearchInterrupted(RuntimeError):
    pass


class ResearchBatchManager:
    def __init__(self, technical, *, import_history=True):
        self.technical = technical
        self.repository = ResearchBatchRepository(technical.repository.db)
        self.repository.recover_interrupted()
        self._pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="research-batch"
        )
        self._capacity = threading.BoundedSemaphore(3)
        self._control = threading.Lock()
        self._stopping = threading.Event()
        self.futures = {}
        if import_history:
            self._import_history()

    def _import_history(self):
        for record in reversed(self.technical.repository.latest(limit=50)):
            result = record.get("result") or {}
            if (
                result.get("status") != "completed"
                or not result.get("run_id")
                or result.get("symbol") != "PORTFOLIO"
            ):
                continue
            batch_id = result["run_id"]
            if self.repository.get(batch_id) is not None:
                continue
            request = {
                "horizon": "legacy",
                "strategy_id": result.get("strategy_id") or "legacy",
                "stock_list": "Historical selection",
                "symbols": result.get("requested_symbols", result.get("symbols", [])),
            }
            self.repository.create(batch_id, "backtest", request)
            self.repository.start(batch_id)
            try:
                report = result.get("report") or build_report(
                    result, kind="backtest", historical=True
                )
                self.repository.finish(batch_id, report)
            except (ReportValidationError, KeyError, TypeError, ValueError):
                self.repository.fail(batch_id, "legacy_evidence_incomplete")

    def submit(self, kind, request):
        settings = horizon_strategy(request["horizon"], request["strategy_id"])
        if kind not in {"scan", "backtest"}:
            raise ValueError("Unknown research batch type")
        if (
            kind == "backtest"
            and settings["short_borrow_available"]
            and request.get("short_borrow_available") is not True
        ):
            raise ValueError(
                "Historical short simulation needs an explicit borrow assumption"
            )
        symbols = self.technical._symbols(request["symbols"])
        request = {**request, "symbols": symbols, "settings": settings}
        with self._control:
            if self._stopping.is_set():
                raise ResearchQueueFull("Research worker is stopping")
            if not self._capacity.acquire(blocking=False):
                raise ResearchQueueFull(
                    "Three research batches are already running or queued"
                )
            batch_id = "batch-" + uuid4().hex
            try:
                self.repository.create(batch_id, kind, request)
                future = self._pool.submit(self._run, batch_id, kind, request)
                self.futures[batch_id] = future
                future.add_done_callback(lambda _future: self._capacity.release())
            except Exception:
                self._capacity.release()
                self.repository.fail(batch_id, "worker_unavailable")
                raise
            if len(self.futures) > 100:
                self.futures = {
                    key: value
                    for key, value in self.futures.items()
                    if not value.done() or key == batch_id
                }
        return self.repository.get(batch_id)

    def _run(self, batch_id, kind, request):
        if self._stopping.is_set() or not self.repository.start(batch_id):
            return

        def progress(phase, completed):
            if self._stopping.is_set():
                raise ResearchInterrupted()
            self.repository.progress(batch_id, phase, completed)

        settings = request["settings"]
        try:
            if kind == "backtest":
                result = PortfolioBacktestService(self.technical).run(
                    symbols=request["symbols"],
                    mode=settings["mode"],
                    strategy_id=settings["strategy_id"],
                    period=settings["period"],
                    short_borrow_available=request.get("short_borrow_available", False),
                    run_id=batch_id,
                    progress=progress,
                    report_horizon=request["horizon"],
                    report_stock_list=request["stock_list"],
                )
                report = result["report"]
            else:
                result = self.technical.scan(
                    symbols=request["symbols"],
                    mode=settings["mode"],
                    strategy_id=settings["strategy_id"],
                    period=settings["period"],
                    top_n=len(request["symbols"]),
                    execute_paper=False,
                    run_id=batch_id,
                    progress=progress,
                )
                report = build_report(
                    result,
                    kind="scan",
                    horizon=request["horizon"],
                    stock_list=request["stock_list"],
                )
            if self._stopping.is_set():
                raise ResearchInterrupted()
            self.repository.finish(batch_id, report)
        except ResearchInterrupted:
            self.repository.interrupt(batch_id)
        except Exception as error:
            code = (
                "report_evidence_invalid"
                if isinstance(error, ReportValidationError)
                else "research_batch_failed"
            )
            self.repository.fail(batch_id, code)
            LOG.warning("research_batch_failed batch=%s code=%s", batch_id, code)

    def close(self, *, wait=False):
        with self._control:
            self._stopping.set()
            for batch_id, future in self.futures.items():
                if not future.done():
                    self.repository.interrupt(batch_id)
            self._pool.shutdown(wait=wait, cancel_futures=True)
