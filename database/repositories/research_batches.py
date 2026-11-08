"""Durable batch lifecycle; report and completed state are published atomically."""

import json
from datetime import UTC, datetime


def utc_now():
    return datetime.now(UTC).isoformat()


class ResearchBatchRepository:
    def __init__(self, db):
        self.db = db

    def create(self, batch_id, kind, request):
        now = utc_now()
        self.db.execute(
            """INSERT INTO research_batches
            (batch_id,kind,status,horizon,strategy_id,stock_list,requested_symbols,created_at,request_json,updated_at)
            VALUES (?,?, 'queued',?,?,?,?,?,?,?)""",
            (
                batch_id,
                kind,
                request["horizon"],
                request["strategy_id"],
                request["stock_list"],
                len(request["symbols"]),
                now,
                json.dumps(request),
                now,
            ),
        )

    def start(self, batch_id):
        cursor = self.db.execute(
            "UPDATE research_batches SET status='running',phase='starting',"
            "started_at=?,updated_at=? WHERE batch_id=? AND status='queued'",
            (utc_now(), utc_now(), batch_id),
        )
        return cursor.rowcount == 1

    def progress(self, batch_id, phase, completed, total=None):
        self.db.execute(
            "UPDATE research_batches SET phase=?,updated_at=?,phase_completed=?,"
            "phase_total=COALESCE(?,requested_symbols),"
            "completed_symbols=CASE WHEN ? IS NULL THEN MIN(?,requested_symbols) "
            "ELSE completed_symbols END "
            "WHERE batch_id=? AND status='running'",
            (phase, utc_now(), completed, total, total, completed, batch_id),
        )

    def finish(self, batch_id, report):
        cursor = self.db.execute(
            """UPDATE research_batches SET status='completed',phase='completed',
            completed_symbols=requested_symbols,phase_completed=requested_symbols,
            phase_total=requested_symbols,finished_at=?,updated_at=?,report_json=?
            WHERE batch_id=? AND status='running'""",
            (utc_now(), utc_now(), json.dumps(report, allow_nan=False), batch_id),
        )
        return cursor.rowcount == 1

    def fail(self, batch_id, code):
        self.db.execute(
            """UPDATE research_batches SET status='failed',phase='failed',
            finished_at=?,updated_at=?,error_code=?
            WHERE batch_id=? AND status IN ('queued','running')""",
            (utc_now(), utc_now(), code, batch_id),
        )

    def recover_interrupted(self):
        self.db.execute(
            """UPDATE research_batches SET status='interrupted',phase='interrupted',
            finished_at=?,updated_at=?,error_code='runtime_restarted'
            WHERE status IN ('queued','running')""",
            (utc_now(), utc_now()),
        )

    def interrupt(self, batch_id):
        self.db.execute(
            """UPDATE research_batches SET status='interrupted',phase='interrupted',
            finished_at=?,updated_at=?,error_code='runtime_shutdown'
            WHERE batch_id=? AND status IN ('queued','running')""",
            (utc_now(), utc_now(), batch_id),
        )

    def latest(self, kind=None, limit=50, offset=0):
        fields = (
            "batch_id,kind,status,horizon,strategy_id,stock_list,requested_symbols,"
            "completed_symbols,phase,created_at,started_at,finished_at,error_code"
            ",updated_at,phase_completed,phase_total"
        )
        if kind is None:
            rows = self.db.fetchall(
                f"SELECT {fields} FROM research_batches "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        else:
            rows = self.db.fetchall(
                f"SELECT {fields} FROM research_batches WHERE kind=? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (kind, limit, offset),
            )
        return [dict(row) for row in rows]

    def get(self, batch_id):
        row = self.db.fetchone(
            "SELECT * FROM research_batches WHERE batch_id=?", (batch_id,)
        )
        if row is None:
            return None
        result = dict(row)
        result["request"] = json.loads(result.pop("request_json"))
        raw = result.pop("report_json")
        result["report"] = json.loads(raw) if raw else None
        return result
