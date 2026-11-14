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

from core.deployment_role import on_render
from database.repositories.research_batches import ResearchBatchRepository
from scanner.strategy_horizons import horizon_strategy
from services.cloud_workload_gate import register_research, research_admission
from services.execution_report import ReportValidationError
from services.research_capacity import (
    CLOUD_BATCH_CANDLE_ROWS,
    CLOUD_MAX_CANDLE_ROWS,
    ResearchCapacityExceeded,
    research_partitions,
    validate_backtest_capacity,
)
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
        self.isolated = on_render() if isolated is None else isolated
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
        register_research(self)
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

    @research_admission
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
        ids = list(
            dict.fromkeys(request.get("strategy_ids") or [request["strategy_id"]])
        )
        if request["strategy_id"] not in ids or len(ids) > 19:
            raise ValueError("Choose the primary strategy in the batch strategy set")
        strategies = [
            horizon_strategy(request["horizon"], strategy, request.get("period"))
            for strategy in ids
        ]
        if (
            kind == "backtest"
            and any(s["short_borrow_available"] for s in strategies)
            and request.get("short_borrow_available") is not True
        ):
            raise ValueError(
                "Historical short simulation needs an explicit borrow assumption"
            )
        from scanner.weekly_floor import STRATEGY_ID as WEEKLY_ID

        shared_weekly = kind == "backtest" and request["strategy_id"] == WEEKLY_ID
        if shared_weekly:
            if ids != [WEEKLY_ID]:
                raise ValueError("The weekly account comparison uses one strategy")
            # Fetch chunks are not independently capitalized portfolios.
            parts = [{"symbols": symbols, "settings": settings}]
        else:
            parts = research_partitions(symbols, settings, strategies)
        if kind == "backtest":
            for part in parts:
                validate_backtest_capacity(part["settings"], len(part["symbols"]))
        request = {**request, "symbols": symbols, "settings": settings}
        if shared_weekly:
            request["weekly_comparison"] = True
            request["account_scope"] = "one_shared_account"
        if len(parts) > 1:
            request["partitions"] = parts
        elif on_render():
            request["max_candle_rows"] = (
                CLOUD_MAX_CANDLE_ROWS if shared_weekly else CLOUD_BATCH_CANDLE_ROWS
            )
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
            if self._stopping.is_set() or not self._active(batch_id):
                raise ResearchInterrupted()
            self.repository.progress(batch_id, phase, completed, total)

        try:
            if request.get("partitions"):
                self._run_partitions(batch_id, kind, request)
                return
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
                "research_row_budget_exceeded"
                if isinstance(error, ResearchCapacityExceeded)
                else (
                    "report_evidence_invalid"
                    if isinstance(error, ReportValidationError)
                    else "research_batch_failed"
                )
            )
            self.repository.fail(batch_id, code)
            LOG.warning("research_batch_failed batch=%s code=%s", batch_id, code)

    def _run_partitions(self, batch_id, kind, request):
        from services.research_partitions import partition_manifest

        children = []
        parts = request["partitions"]
        for index, part in enumerate(parts):
            if self._stopping.is_set() or not self._active(batch_id):
                raise ResearchInterrupted()
            child_id = f"{batch_id}-p{index + 1:03d}"
            child_request = {
                **{
                    key: value
                    for key, value in request.items()
                    if key not in {"partitions", "strategy_ids"}
                },
                "symbols": part["symbols"],
                "settings": part["settings"],
                "strategy_id": part["settings"]["strategy_id"],
                "parent_batch_id": batch_id,
                "partition_scope": "independent_portfolios",
                **({"max_candle_rows": CLOUD_BATCH_CANDLE_ROWS} if on_render() else {}),
            }
            self.repository.progress(batch_id, "partitions", index, len(parts))
            self.repository.create(child_id, kind, child_request)
            # The existing single-worker queue owns the entire campaign. A child
            # finishes before another child (or queued research request) starts.
            self._run(child_id, kind, child_request)
            child = self.repository.get(child_id)
            if child["status"] != "completed":
                raise RuntimeError("A research partition did not complete")
            children.append(child)
            # Keep only the compact manifest evidence, not all child workbooks.
            children[-1] = {
                **child,
                "report": {
                    "metrics": child["report"].get("metrics", {}),
                    "sha256": child["report"]["sha256"],
                },
            }
        self._complete(batch_id, partition_manifest(batch_id, kind, request, children))

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
                cancelled = not self._active(batch_id)
                if self._stopping.wait(0.5) or cancelled or time.monotonic() > deadline:
                    child.terminate()
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=3)
                    if self._stopping.is_set() or cancelled:
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

    def _active(self, batch_id):
        row = self.repository.db.fetchone(
            "SELECT status FROM research_batches WHERE batch_id=?", (batch_id,)
        )
        return row is not None and row["status"] == "running"

    def cancel(self, batch_id):
        batch = self.repository.get(batch_id)
        if batch is None:
            raise ValueError("Unknown research batch")
        self.repository.interrupt(batch_id, code="operator_cancelled")
        for index in range(len(batch["request"].get("partitions", []))):
            self.repository.interrupt(
                f"{batch_id}-p{index + 1:03d}", code="operator_cancelled"
            )
        future = self.futures.get(batch_id)
        if future is not None:
            future.cancel()
        return self.repository.get(batch_id)

    def close(self, *, wait=False):
        with self._control:
            self._stopping.set()
            for batch_id, future in self.futures.items():
                if not future.done():
                    self.repository.interrupt(batch_id)
            self._pool.shutdown(wait=wait, cancel_futures=True)
