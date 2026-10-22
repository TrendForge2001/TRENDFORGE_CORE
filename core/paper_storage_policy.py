"""Paper entry storage admission, independent of API and broker interfaces."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.storage_config import (
    production_runtime_enabled,
    resolve_storage,
    storage_health,
)

EPHEMERAL_SIMULATION_ENV = "TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION"


def paper_entry_storage_policy(
    *,
    runtime_database_path: str | None = None,
    production: bool | None = None,
) -> dict[str, Any]:
    production = production_runtime_enabled() if production is None else production
    report: dict[str, Any] = {
        "production": production,
        "entry_allowed": False,
        "mode": "blocked",
        "verified_persistent": False,
        "ephemeral_simulation": False,
        "reason": "persistent_storage_required",
        "message": "New paper entries require verified persistent storage.",
    }
    if not production:
        return {
            **report,
            "entry_allowed": True,
            "mode": "local_simulation",
            "reason": "local_simulation",
            "message": "Local paper simulation; durability is not verified.",
        }
    try:
        if (
            runtime_database_path is not None
            and Path(runtime_database_path).expanduser().resolve()
            != resolve_storage().database.expanduser().resolve()
        ):
            return {
                **report,
                "reason": "runtime_database_mismatch",
                "message": "Paper runtime database differs from the configured database; new entries are blocked.",
            }
        verified = storage_health().get("verified_persistent") is True
    except Exception:
        return {
            **report,
            "reason": "storage_verification_unavailable",
            "message": "Storage verification is unavailable; new paper entries are blocked.",
        }
    if verified:
        return {
            **report,
            "entry_allowed": True,
            "mode": "durable",
            "verified_persistent": True,
            "reason": "verified_persistent_storage",
            "message": "Paper storage mount and restart recovery are verified.",
        }
    if os.getenv(EPHEMERAL_SIMULATION_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return {
            **report,
            "entry_allowed": True,
            "mode": "ephemeral_simulation",
            "ephemeral_simulation": True,
            "reason": "explicit_ephemeral_simulation",
            "message": "Ephemeral simulation: positions, history and risk state may be lost when the service restarts.",
        }
    return report
