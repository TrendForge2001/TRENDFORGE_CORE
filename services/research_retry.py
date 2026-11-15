"""Explicit, durable, at-most-once replay of an owner's failed research request."""

import asyncio
import json
import logging
import os
import re

from scanner.weekly_floor import STRATEGY_ID

LOG = logging.getLogger(__name__)


def request_research_retry(app):
    raw = os.getenv("TRENDFORGE_RESEARCH_RETRY", "")
    if not raw:
        return None
    # This operator request cannot activate a PC clone or a different service.
    if os.getenv("RENDER_SERVICE_ID") != "srv-db1tb7jncjis73c994e0":
        return None
    try:
        if len(raw) > 2048:
            raise ValueError
        intent = json.loads(raw)
        if set(intent) != {"request_id", "source_batch_id"}:
            raise ValueError
        request_id, source = intent["request_id"], intent["source_batch_id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
            raise ValueError
        if source != "latest_failed_weekly_nifty100" and not re.fullmatch(
            r"batch-[a-f0-9]{32}", source
        ):
            raise ValueError
        manager = app.state.research_manager_getter()
        repo, db = manager.repository, manager.repository.db
        db.execute("""CREATE TABLE IF NOT EXISTS research_retry_requests (
            request_id TEXT PRIMARY KEY, source_batch_id TEXT NOT NULL,
            retry_batch_id TEXT, status TEXT NOT NULL)""")
        # Consume BEFORE submission. A crash in between cannot submit twice.
        claimed = db.execute(
            "INSERT OR IGNORE INTO research_retry_requests "
            "(request_id,source_batch_id,status) VALUES (?,?,'claimed')",
            (request_id, source),
        ).rowcount
        if not claimed:
            LOG.warning("research_retry request=%s status=already_consumed", request_id)
            return None
        if source == "latest_failed_weekly_nifty100":
            source = next(
                (
                    r["batch_id"]
                    for r in repo.latest("backtest", limit=200)
                    if r["status"] == "failed"
                    and r["strategy_id"] == STRATEGY_ID
                    and r["stock_list"] == "NIFTY 100"
                ),
                None,
            )
        previous = repo.get(source) if source else None
        if (
            not previous
            or previous["status"] != "failed"
            or previous["kind"] != "backtest"
            or previous["strategy_id"] != STRATEGY_ID
        ):
            raise ValueError
        original = previous["request"]
        request = {
            k: original[k] for k in ("symbols", "strategy_id", "horizon", "stock_list")
        }
        request["period"] = original.get("period") or original["settings"]["period"]
        request["retry_of"] = source
        retry = manager.submit("backtest", request)
        db.execute(
            "UPDATE research_retry_requests SET source_batch_id=?, "
            "retry_batch_id=?,status='submitted' WHERE request_id=?",
            (source, retry["batch_id"], request_id),
        )
        LOG.warning(
            "research_retry request=%s source=%s batch=%s status=submitted "
            "stocks=%s period=%s orders_submitted=0",
            request_id,
            source,
            retry["batch_id"],
            len(request["symbols"]),
            request["period"],
        )

        def finished(_future):
            result = repo.get(retry["batch_id"]) or {}
            db.execute(
                "UPDATE research_retry_requests SET status=? WHERE request_id=?",
                (result.get("status", "unknown"), request_id),
            )
            LOG.warning(
                "research_retry request=%s batch=%s status=%s code=%s "
                "diagnostic=%s orders_submitted=0",
                request_id,
                retry["batch_id"],
                result.get("status"),
                result.get("error_code"),
                json.dumps(result.get("diagnostic"), sort_keys=True),
            )
            if result.get("status") == "completed":
                report = result["report"]
                summary = [
                    {
                        k: row.get(k)
                        for k in (
                            "variant",
                            "net_profit",
                            "max_drawdown_pct",
                            "total_trades",
                            "skipped_trades",
                        )
                    }
                    for row in report.get("comparisons", [])
                ]
                LOG.warning(
                    "research_retry_report batch=%s sha256=%s variants=%s",
                    retry["batch_id"],
                    report["sha256"],
                    json.dumps(summary, sort_keys=True),
                )

        manager.futures[retry["batch_id"]].add_done_callback(finished)
        return retry["batch_id"]
    except Exception as error:
        from services.research_failure import failure_diagnostic

        LOG.warning(
            "research_retry status=not_submitted diagnostic=%s orders_submitted=0",
            json.dumps(failure_diagnostic(error), sort_keys=True),
        )
        return None


def start_research_retry(app):
    if not os.getenv("TRENDFORGE_RESEARCH_RETRY"):
        return None
    return asyncio.create_task(
        asyncio.to_thread(request_research_retry, app), name="explicit-research-retry"
    )
