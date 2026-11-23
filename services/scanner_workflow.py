"""Durable research handoffs. Never call a paper or broker order service."""

import hashlib
import json
import threading
from collections import Counter
from datetime import UTC, datetime
from uuid import uuid4

from scanner.strategy_horizons import horizon_strategy
from scanner.strategy_registry import get_strategy

KEEP_RUNS = 10


def now():
    return datetime.now(UTC).isoformat()


def leaf_batches(repository, batch, *, depth=0):
    if depth > 3:
        raise ValueError("Research partition nesting is invalid")
    report = batch.get("report") or {}
    if report.get("report_type") != "research_partition_manifest":
        yield batch
        return
    for row in report.get("rows", []):
        child = repository.get(row["batch_id"])
        if (
            not child
            or child["status"] != "completed"
            or child["request"].get("parent_batch_id") != batch["batch_id"]
        ):
            raise ValueError("Research partition evidence is incomplete")
        yield from leaf_batches(repository, child, depth=depth + 1)


class ScannerWorkflow:
    def __init__(self, repository, archive=None):
        self.repository, self.db, self.archive = repository, repository.db, archive
        self.db.execute("""CREATE TABLE IF NOT EXISTS scanner_workflow_runs(
            run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, stock_list TEXT NOT NULL,
            fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS scanner_retired_runs(
            run_id TEXT PRIMARY KEY, retired_at TEXT NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS scanner_backtest_queue(
            queue_id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, symbol TEXT NOT NULL,
            strategy_id TEXT NOT NULL, horizon TEXT NOT NULL, stock_list TEXT NOT NULL,
            origin_signal TEXT NOT NULL, period TEXT NOT NULL, created_at TEXT NOT NULL,
            provenance_json TEXT NOT NULL, job_id TEXT)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS scanner_backtest_jobs(
            job_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, horizon TEXT NOT NULL,
            period TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL,
            batch_id TEXT, error_code TEXT)""")

    def record(self, batch):
        if (
            batch["kind"] != "scan"
            or batch["status"] != "completed"
            or not batch.get("report")
        ):
            return
        if batch["request"].get("parent_batch_id"):
            return
        run_id = batch["batch_id"]
        if self.db.fetchone(
            "SELECT 1 FROM scanner_retired_runs WHERE run_id=?", (run_id,)
        ):
            return
        rows, queues, archive_ids = [], [], [run_id]
        for child in leaf_batches(self.repository, batch):
            archive_ids.append(child["batch_id"])
            report = child["report"]
            for raw in report.get("rows", []):
                strategy = raw.get("strategy_id") or child["strategy_id"]
                horizon = raw.get("horizon") or child["horizon"]
                signal = str(raw.get("signal") or "WAIT").upper()
                row = {
                    **raw,
                    "scan_id": run_id,
                    "strategy_id": strategy,
                    "horizon": horizon,
                    "source_stock_list": batch["stock_list"],
                    "signal": signal,
                    "scan_generated_at": report["generated_at"],
                }
                try:
                    row["strategy_name"] = get_strategy(strategy)["name"]
                except ValueError:
                    row["strategy_name"] = strategy
                rows.append(row)
                if (
                    signal not in {"BUY", "SELL", "EXIT"}
                    or raw.get("error")
                    or raw.get("data_status") in {"STALE", "UNAVAILABLE", "WARMING_UP"}
                ):
                    continue
                try:
                    settings = horizon_strategy(horizon, strategy)
                except ValueError:
                    continue
                symbol = row.get("symbol")
                if not isinstance(symbol, str) or not symbol:
                    continue
                identifier = hashlib.sha256(
                    f"{run_id}|{symbol}|{strategy}|{horizon}".encode()
                ).hexdigest()
                queues.append(
                    (
                        identifier,
                        run_id,
                        symbol,
                        strategy,
                        horizon,
                        batch["stock_list"],
                        signal,
                        settings["period"],
                        report["generated_at"],
                        json.dumps(
                            {
                                key: row.get(key)
                                for key in (
                                    "symbol",
                                    "strategy_id",
                                    "strategy_name",
                                    "horizon",
                                    "signal",
                                    "entry",
                                    "stoploss",
                                    "target2",
                                    "bar_at",
                                    "score",
                                    "source_stock_list",
                                    "scan_generated_at",
                                    "registry_version",
                                    "data_status",
                                )
                            },
                            allow_nan=False,
                        ),
                    )
                )
        payload = {
            "run_id": run_id,
            "created_at": batch["report"]["generated_at"],
            "stock_list": batch["stock_list"],
            "rows": rows,
            "counts": dict(Counter(row["signal"] for row in rows)),
            "archive_ids": sorted(set(archive_ids)),
        }
        encoded = json.dumps(payload, allow_nan=False)
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        with self.db._lock, self.db.conn:
            existing = self.db.conn.execute(
                "SELECT fingerprint FROM scanner_workflow_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if existing and existing[0] != fingerprint:
                raise ValueError(
                    "A scanner run cannot be replaced by different evidence"
                )
            self.db.conn.execute(
                "INSERT OR IGNORE INTO scanner_workflow_runs VALUES(?,?,?,?,?)",
                (
                    run_id,
                    payload["created_at"],
                    batch["stock_list"],
                    fingerprint,
                    encoded,
                ),
            )
            self.db.conn.executemany(
                """INSERT OR IGNORE INTO scanner_backtest_queue(
                queue_id,scan_id,symbol,strategy_id,horizon,stock_list,
                origin_signal,period,created_at,provenance_json)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                queues,
            )
        self.prune()

    def reconcile(self):
        rows = self.db.fetchall("""SELECT batch_id FROM research_batches
            WHERE kind='scan'
            AND status='completed' AND report_json IS NOT NULL
            AND json_extract(request_json,'$.parent_batch_id') IS NULL
            ORDER BY created_at DESC LIMIT 10""")
        for row in reversed(rows):
            if not self.db.fetchone(
                "SELECT 1 FROM scanner_workflow_runs WHERE run_id=?", (row[0],)
            ):
                self.record(self.repository.get(row[0]))
        self.prune()

    def prune(self):
        # Serialize file retirement with the DB tombstone commit across processes.
        with self.db._lock:
            self.db.conn.execute("BEGIN IMMEDIATE")
            try:
                old = self.db.conn.execute(
                    "SELECT run_id,payload_json FROM scanner_workflow_runs "
                    "ORDER BY created_at DESC,run_id DESC LIMIT -1 OFFSET ?",
                    (KEEP_RUNS,),
                ).fetchall()
                ids = set()
                for row in old:
                    ids.update(json.loads(row[1])["archive_ids"])
                # Retire pre-upgrade scan payloads too, once the newest ten
                # top-level runs have been journalled. Traverse IDs in SQL so
                # large historical result rows never need to be loaded here.
                count = self.db.conn.execute(
                    "SELECT COUNT(*) FROM scanner_workflow_runs"
                ).fetchone()[0]
                if count >= KEEP_RUNS:
                    legacy = self.db.conn.execute("""
                        WITH RECURSIVE retired(batch_id) AS (
                            SELECT batch_id FROM research_batches
                            WHERE kind='scan' AND status='completed'
                            AND report_json IS NOT NULL
                            AND json_extract(request_json,'$.parent_batch_id') IS NULL
                            AND batch_id NOT IN (
                                SELECT run_id FROM scanner_workflow_runs
                                ORDER BY created_at DESC,run_id DESC LIMIT 10
                            )
                            UNION
                            SELECT child.batch_id FROM research_batches child
                            JOIN retired parent ON json_extract(
                                child.request_json,'$.parent_batch_id'
                            )=parent.batch_id WHERE child.kind='scan'
                        ) SELECT batch_id FROM retired
                    """).fetchall()
                    ids.update(row[0] for row in legacy)
                if ids and self.archive:
                    self.archive.retire_scans(ids)
                self.db.conn.executemany(
                    "INSERT OR IGNORE INTO scanner_retired_runs VALUES(?,?)",
                    [(key, now()) for key in ids],
                )
                self.db.conn.executemany(
                    (
                        "UPDATE research_batches SET "
                        "report_json=NULL,error_code='report_retained_out' WHERE "
                        "batch_id=? AND kind='scan'"
                    ),
                    [(key,) for key in ids],
                )
                self.db.conn.executemany(
                    "DELETE FROM scanner_workflow_runs WHERE run_id=?",
                    [(row[0],) for row in old],
                )
                self.db.conn.commit()
            except BaseException:
                self.db.conn.rollback()
                raise

    def reports(self):
        self.reconcile()
        rows = self.db.fetchall(
            (
                "SELECT payload_json FROM scanner_workflow_runs ORDER BY "
                "created_at DESC,run_id DESC LIMIT "
                "?"
            ),
            (KEEP_RUNS,),
        )
        return [
            {
                key: value
                for key, value in json.loads(row[0]).items()
                if key not in {"rows", "archive_ids"}
            }
            for row in rows
        ]

    def report(self, run_id):
        self.reconcile()
        row = self.db.fetchone(
            "SELECT payload_json FROM scanner_workflow_runs WHERE run_id=?", (run_id,)
        )
        if not row:
            raise KeyError("Scanner report is unavailable or outside retention")
        return json.loads(row[0])

    def queue(self):
        return [
            dict(row)
            for row in self.db.fetchall(
                "SELECT * FROM scanner_backtest_queue ORDER BY created_at,queue_id"
            )
        ]

    def jobs(self):
        rows = [
            dict(row)
            for row in self.db.fetchall(
                "SELECT * FROM scanner_backtest_jobs ORDER BY created_at DESC"
            )
        ]
        for row in rows:
            if not row["batch_id"]:
                matches = self.db.fetchall(
                    (
                        "SELECT batch_id FROM research_batches WHERE "
                        "json_extract(request_json,'$.workflow_job_id')=?"
                    ),
                    (row["job_id"],),
                )
                if len(matches) == 1:
                    row["batch_id"] = matches[0][0]
                    self.db.execute(
                        "UPDATE scanner_backtest_jobs SET batch_id=? WHERE job_id=?",
                        (row["batch_id"], row["job_id"]),
                    )
            if row["batch_id"]:
                batch = self.db.fetchone(
                    "SELECT status,error_code FROM research_batches WHERE batch_id=?",
                    (row["batch_id"],),
                )
                if batch:
                    row["status"], row["error_code"] = batch[0], batch[1]
                else:
                    row["status"], row["error_code"] = (
                        "interrupted",
                        "research_batch_missing",
                    )
        return rows


class ScannerBacktestDispatcher:
    def __init__(self, manager):
        self.manager = manager
        self.workflow = ScannerWorkflow(manager.repository, manager.archive)
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.thread = None

    def start(self):
        self.workflow.reconcile()
        with self.lock:
            if self.thread and self.thread.is_alive():
                return {"status": "running"}
            for job in self.workflow.jobs():
                if job["status"] in {"failed", "interrupted", "blocked"} or (
                    job["status"] == "submitting" and not job["batch_id"]
                ):
                    self.workflow.db.execute(
                        "UPDATE scanner_backtest_queue SET job_id=NULL WHERE job_id=?",
                        (job["job_id"],),
                    )
                    self.workflow.db.execute(
                        (
                            "UPDATE scanner_backtest_jobs SET status='interrupted' "
                            "WHERE "
                            "job_id=? AND status='submitting'"
                        ),
                        (job["job_id"],),
                    )
            self.stop.clear()
            self.thread = threading.Thread(
                target=self._run, daemon=True, name="scanner-backtest-handoff"
            )
            self.thread.start()
        return {"status": "started"}

    def _run(self):
        while not self.stop.is_set():
            if any(
                job["status"] in {"running", "queued"} for job in self.workflow.jobs()
            ):
                self.stop.wait(1)
                continue
            pending = [row for row in self.workflow.queue() if row["job_id"] is None]
            if not pending:
                return
            first = pending[0]
            group = [
                row
                for row in pending
                if (row["strategy_id"], row["horizon"], row["period"])
                == (first["strategy_id"], first["horizon"], first["period"])
            ]
            job_id = "queue-" + uuid4().hex
            with self.workflow.db._lock, self.workflow.db.conn:
                self.workflow.db.conn.execute(
                    (
                        "INSERT INTO scanner_backtest_jobs "
                        "VALUES(?,?,?,?,?,'submitting',NULL,NULL)"
                    ),
                    (
                        job_id,
                        first["strategy_id"],
                        first["horizon"],
                        first["period"],
                        now(),
                    ),
                )
                self.workflow.db.conn.executemany(
                    (
                        "UPDATE scanner_backtest_queue SET job_id=? WHERE queue_id=? "
                        "AND job_id IS NULL"
                    ),
                    [(job_id, row["queue_id"]) for row in group],
                )
                assigned = {
                    row[0]
                    for row in self.workflow.db.conn.execute(
                        "SELECT queue_id FROM scanner_backtest_queue WHERE job_id=?",
                        (job_id,),
                    ).fetchall()
                }
                group = [row for row in group if row["queue_id"] in assigned]
                if not group:
                    self.workflow.db.conn.execute(
                        "DELETE FROM scanner_backtest_jobs WHERE job_id=?", (job_id,)
                    )
                    return
            try:
                batch = self.manager.submit(
                    "backtest",
                    {
                        "symbols": sorted({row["symbol"] for row in group}),
                        "strategy_id": first["strategy_id"],
                        "horizon": first["horizon"],
                        "period": first["period"],
                        "stock_list": "SCANNER QUEUE",
                        "short_borrow_available": False,
                        "workflow_job_id": job_id,
                        "source_stock_lists": sorted(
                            {row["stock_list"] for row in group}
                        ),
                    },
                )
                self.workflow.db.execute(
                    (
                        "UPDATE scanner_backtest_jobs SET status=?,batch_id=? WHERE "
                        "job_id=?"
                    ),
                    (batch["status"], batch["batch_id"], job_id),
                )
                while not self.stop.wait(1):
                    state = self.manager.repository.get(batch["batch_id"])
                    if state["status"] not in {"queued", "running"}:
                        break
            except Exception as exc:
                # A rejected workload admission leaves candidates available;
                # no paper worker is disabled to make room for research.
                self.workflow.db.execute(
                    (
                        "UPDATE scanner_backtest_jobs SET "
                        "status='blocked',error_code=? WHERE "
                        "job_id=?"
                    ),
                    (type(exc).__name__, job_id),
                )
                self.workflow.db.execute(
                    "UPDATE scanner_backtest_queue SET job_id=NULL WHERE job_id=?",
                    (job_id,),
                )
                return

    def close(self):
        self.stop.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)


def record_completed_scan(repository, archive, batch_id):
    meta = repository.db.fetchone(
        (
            "SELECT kind,json_extract(request_json,'$.parent_batch_id') "
            "FROM research_batches WHERE "
            "batch_id=?"
        ),
        (batch_id,),
    )
    if meta and meta[0] == "scan" and meta[1] is None:
        ScannerWorkflow(repository, archive).record(repository.get(batch_id))
