"""Daily, owner-enabled public-data refresh independent of paper execution."""

import asyncio
import json
import logging
import os
import re
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from core.storage_config import production_runtime_enabled, storage_health
from database.repositories.big_shark_repository import BigSharkRepository
from services.big_shark_portfolio import bootstrap_from_environment
from services.big_shark_public_feed import refresh_public_sources

LOG = logging.getLogger("trendforge.institutional.sources")


def refresh_requested(
    *, now=None, provider=None, repository_factory=BigSharkRepository
):
    """Consume one private operator request; never enable daily or paper automation."""
    request = os.getenv("TRENDFORGE_BIG_SHARK_REFRESH_REQUEST", "")
    if not request:
        return {"status": "disabled"}
    if not re.fullmatch(r"[a-f0-9]{32}", request):
        return {"status": "invalid_request"}
    if (
        production_runtime_enabled()
        and storage_health().get("verified_persistent") is not True
    ):
        return {"status": "storage_unverified"}
    repo = repository_factory()
    key = "startup-refresh:" + request
    try:
        if not repo.claim_source_state({"status": "claimed"}, key):
            return {"status": "already_consumed"}
        bootstrap_from_environment(repo)
        config = repo.source_state("config") or {}
        result = refresh_public_sources(
            repo,
            provider=provider,
            now=now,
            source=config.get("source", "NSE_BULK"),
            metric=config.get("metric", "quantity"),
            aliases=config.get("aliases", {}),
        )
        snapshot = repo.latest() or {}
        summary = {
            "status": result["status"],
            "failures": result.get("failures", {}),
            "portfolio_loaded": bool(snapshot),
            "investors": len(snapshot.get("investor_rows", [])),
            "stocks": len(snapshot.get("signals", [])),
            "trade_records": result.get("trades", {}).get("records_received", 0),
            "matched_records": result.get("trades", {}).get("matched_records", 0),
            "broker_orders_allowed": False,
            "paper_automation_changed": False,
        }
        repo.save_source_state(summary, key)
        return summary
    except Exception:
        repo.save_source_state({"status": "failed"}, key)
        raise
    finally:
        repo.close()


def refresh_if_due(*, now=None, provider=None, repository_factory=BigSharkRepository):
    now = now or datetime.now(UTC)
    if (
        production_runtime_enabled()
        and storage_health().get("verified_persistent") is not True
    ):
        return {"status": "storage_unverified"}
    repo = repository_factory()
    try:
        config = repo.source_state("config") or {}
        if config.get("enabled") is not True:
            return {"status": "disabled"}
        state = repo.source_state() or {}
        stamp = state.get("checked_at")
        if stamp:
            try:
                last = datetime.fromisoformat(stamp)
                interval = timedelta(hours=1 if state.get("failures") else 24)
                if now - last < interval:
                    return {"status": "not_due"}
            except (TypeError, ValueError):
                return {"status": "invalid_refresh_timestamp"}
        result = refresh_public_sources(
            repo,
            provider=provider,
            now=now,
            source=config.get("source", "NSE_BULK"),
            metric=config.get("metric", "quantity"),
            aliases=config.get("aliases", {}),
        )
        return {"status": result["status"], "failures": result.get("failures", {})}
    finally:
        repo.close()


def start_public_source_scheduler():
    async def loop():
        await asyncio.sleep(30)
        try:
            result = await asyncio.to_thread(refresh_requested)
            if result["status"] not in {"disabled", "already_consumed"}:
                LOG.warning("institutional_requested_refresh %s", json.dumps(result))
        except Exception:  # noqa: BLE001 - request details and private state stay private
            LOG.warning("institutional_requested_refresh status=failed")
        while True:
            try:
                result = await asyncio.to_thread(refresh_if_due)
                if result["status"] not in {"disabled", "not_due"}:
                    LOG.warning(
                        "institutional_public_refresh status=%s", result["status"]
                    )
            except Exception:  # noqa: BLE001 - private state/provider details stay private
                LOG.warning("institutional_public_refresh status=unavailable")
            await asyncio.sleep(300)

    return asyncio.create_task(loop(), name="big-shark-public-source-refresh")


async def stop_public_source_scheduler(task):
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
