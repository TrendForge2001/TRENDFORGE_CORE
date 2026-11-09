"""Opt-in Render paper host: retain its existing book and keep broker writes off."""

import atexit
import os
import secrets
from contextlib import ExitStack

from core.pc_paper_policy import policy_environment
from core.storage_config import resolve_storage
from scripts.local_engine_runtime import exclusive_lock
from services.cloud_paper_storage import prepare_cloud_storage

_LOCK = ExitStack()
_PREPARED = False


def prepare_render_paper():
    global _PREPARED
    if os.getenv("TRENDFORGE_CLOUD_PAPER_EXECUTION", "false").lower() != "true":
        return "not_configured"
    if os.getenv("RENDER", "false").lower() != "true":
        raise ValueError("The cloud paper host must run on Render")
    if _PREPARED:
        return "already_prepared"
    os.environ.update(policy_environment())
    os.environ.update(
        {
            "TRENDFORGE_CLOUD_READ_ONLY": "false",
            "TRENDFORGE_PRODUCTION_RUNTIME": "true",
            "TRENDFORGE_UNIFIED_UI_ENABLED": "true",
            "TRENDFORGE_LIVE_TRADING_ENABLED": "false",
            "TRENDFORGE_PAPER_TRADING_ENABLED": "true",
            "TRENDFORGE_PAPER_AUTO_ENTRY_ENABLED": "true",
            "TRENDFORGE_PAPER_MONITOR_ENABLED": "true",
            "TRENDFORGE_PAPER_MONITOR_INTERVAL_SECONDS": "15",
            "TRENDFORGE_STRATEGY_PAPER_MONITOR_ENABLED": "true",
            "TRENDFORGE_TECHNICAL_AUTO_SCAN_ENABLED": "false",
            "TRENDFORGE_STORAGE_RECOVERY_VERIFIED": "false",
            "TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION": "false",
            "TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES": "false",
            "WEB_CONCURRENCY": "1",
        }
    )
    # A missing or damaged book/proof blocks startup; never replace a PC ledger
    # or invent an empty cloud trading book to make readiness look green.
    with ExitStack() as pending:
        pending.enter_context(
            exclusive_lock(resolve_storage().root / "paper-cloud-runtime.lock")
        )
        verified = prepare_cloud_storage(boot_id=secrets.token_hex(16))
        os.environ["TRENDFORGE_STORAGE_RECOVERY_VERIFIED"] = str(verified).lower()
        _LOCK.enter_context(pending.pop_all())
    atexit.register(_LOCK.close)
    _PREPARED = True
    print(
        "TRENDFORGE_PAPER_HOST runtime=render automation=off "
        f"storage_verified={str(verified).lower()} broker_orders_allowed=false",
        flush=True,
    )
    return "restart_verified" if verified else "restart_required"
