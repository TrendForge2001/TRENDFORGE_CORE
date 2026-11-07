"""Optional startup authentication evidence; profile read only, no account values."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from providers.kite_diagnostics import MESSAGES, session_failure

LOG = logging.getLogger("trendforge.kite.session")


def start_session_probe(app: Any, broker_getter: Callable[[], Any]):
    if os.getenv("TRENDFORGE_KITE_SESSION_PROBE_ON_START", "false").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None

    async def probe():
        def check():
            try:
                health = broker_getter().health()
                authenticated = (
                    isinstance(health, dict) and health.get("authenticated") is True
                )
                code = (
                    "ok"
                    if authenticated
                    else health.get("auth_error_code", "probe_failed")
                    if isinstance(health, dict)
                    else "probe_failed"
                )
                return (
                    authenticated,
                    code if code == "ok" or code in MESSAGES else "probe_failed",
                )
            except Exception as error:
                return False, session_failure(error)["code"]

        authenticated, code = await asyncio.to_thread(check)
        app.state.kite_session_probe = {"authenticated": authenticated, "code": code}
        LOG.warning(
            "kite_session_probe authenticated=%s code=%s orders_submitted=0",
            str(authenticated).lower(),
            code,
        )

    return asyncio.create_task(probe(), name="kite-read-only-session-probe")


async def stop_session_probe(task) -> None:
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
