"""Verify mounted cloud research storage using evidence from a previous boot."""

from __future__ import annotations

import logging
import os
import secrets
import sqlite3

from core.deployment_role import cloud_read_only
from core.storage_config import production_runtime_enabled
from services.cloud_paper_storage import prepare_cloud_storage

_BOOT_ID = secrets.token_hex(16)
_LOG = logging.getLogger(__name__)
_RECOVERY = "TRENDFORGE_STORAGE_RECOVERY_VERIFIED"


def verify_research_storage_boot() -> str:
    """Inspect the initialized book; never initialize or replace one here.

    The shared verifier matches a nonce in SQLite and a flushed disk file.
    A second call in the same process cannot count as a server restart.
    This check does not alter the deployment role or enable any trading.
    """
    if not production_runtime_enabled() or not cloud_read_only():
        return "not_applicable"
    os.environ[_RECOVERY] = "false"
    if not os.getenv("TRENDFORGE_PERSISTENT_MOUNT", "").strip():
        return "not_configured"
    try:
        verified = prepare_cloud_storage(boot_id=_BOOT_ID)
    except (OSError, ValueError, sqlite3.Error):
        _LOG.warning("research_storage_recovery status=unverified")
        return "unverified"
    os.environ[_RECOVERY] = str(verified).lower()
    status = "restart_verified" if verified else "restart_required"
    _LOG.info("research_storage_recovery status=%s", status)
    return status
