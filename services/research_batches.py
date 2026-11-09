"""Bounded background research; no order execution or automatic restart replay."""

import logging
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from core.deployment_role import cloud_read_only
from database.repositories.research_batches import ResearchBatchRepository
from scanner.strategy_horizons import horizon_strategy
from services.execution_report import ReportValidationError
from services.research_capacity import validate_backtest_capacity
from services.research_recovery import recover_seed
from services.research_report import build_report
from services.research_storage import complete_batch, report_archive

LOG = logging.getLogger(__name__)


class ResearchQueueFull(ValueError):
    pass


class ResearchInterrupted(RuntimeError):
    pass


class ResearchBatchManager:
    def __init__(
        self,
        technical,
        *,
        import_history=True,
        isolated=None,
        worker_module="services.research_worker",
    ):
        self.isolated = cloud_read_only() if isolated is None else isolated
        self.worker_module = worker_module
        self.technical = technical
        self.repository = ResearchBatchRepository(technical.repository.db)
        self.repository.recover_interrupted()
        database_path = str(technical.repository.db.db_path)
        self.archive = report_archive(database_path)
        self.archive_recovery = (
            self.archive.restore(self.repository)
            if self.archive
            else {"restored": 0, "invalid": 0}
        )
        self.seed_recovery = recover_seed(self.repository, self.archive)
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
                self._complete(batch_id, report)
            except (ReportValidationError, KeyError, TypeError, ValueError):
                self.repository.fail(batch_id, "legacy_evidence_incomplete")

    def submit(self, kind, request):
        settings = horizon_strategy(
            request["horizon"], request["strategy_id"], request.get("period")
        )
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
        if kind == "backtest":
            validate_backtest_capacity(settings, len(symbols))
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

        def progress(phase, completed, total=None):
            if self._stopping.is_set():
                raise ResearchInterrupted()
            self.repository.progress(batch_id, phase, completed, total)

        try:
            if self.isolated:
                self._run_isolated(batch_id)
                return
            from services.research_execution import execute_research

            report = execute_research(self.technical, batch_id, kind, request, progress)
            if self._stopping.is_set():
                raise ResearchInterrupted()
            self._complete(batch_id, report)
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

    def _run_isolated(self, batch_id):
        # Candle frames and reports stay in the child. SQLite carries only
        # committed progress/results; no huge pickle or JSON work on the UI GIL.
        env = {
            **os.environ,
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "TRENDFORGE_LIVE_TRADING_ENABLED": "false",
            "TRENDFORGE_PAPER_TRADING_ENABLED": "false",
            "TRENDFORGE_PAPER_AUTO_ENTRY_ENABLED": "false",
        }
        command = [
            sys.executable,
            "-m",
            self.worker_module,
            "--database",
            str(Path(self.repository.db.db_path).resolve()),
            "--batch-id",
            batch_id,
            "--parent-pid",
            str(os.getpid()),
        ]
        deadline = time.monotonic() + 1800
        with subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) as child:
            while child.poll() is None:
                if self._stopping.wait(0.5) or time.monotonic() > deadline:
                    child.terminate()
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=3)
                    if self._stopping.is_set():
                        raise ResearchInterrupted()
                    self.repository.fail(batch_id, "research_time_limit")
                    return
            # A crash/OOM in the research child must not kill the web process
            # or leave a running batch without an owner.
            self.repository.fail(batch_id, "research_worker_exited")
            LOG.info(
                "research_worker_exit batch=%s exit=%s", batch_id, child.returncode
            )

    def _complete(self, batch_id, report):
        return complete_batch(self.repository, self.archive, batch_id, report)

    def close(self, *, wait=False):
        with self._control:
            self._stopping.set()
            for batch_id, future in self.futures.items():
                if not future.done():
                    self.repository.interrupt(batch_id)
            self._pool.shutdown(wait=wait, cancel_futures=True)
