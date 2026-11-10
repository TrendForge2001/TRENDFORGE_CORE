"""Startup session diagnostics and a separately configured owner order request."""

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
        if os.getenv("TRENDFORGE_OWNER_KITE_ORDER_TEST", ""):
            from services.owner_kite_order_test import run_configured_order_test

            try:
                app.state.owner_kite_order_test = await asyncio.to_thread(
                    run_configured_order_test
                )
            except Exception:
                LOG.warning(
                    "owner_kite_order_test status=unavailable "
                    "check_saved_receipt_or_broker_orders=true"
                )
        if (
            authenticated
            and os.getenv("TRENDFORGE_SCANNER_INPUT_PROBE_ON_START", "false").lower()
            == "true"
        ):
            from services.kite_market_preflight import scanner_input_checks

            try:
                report = await asyncio.to_thread(
                    scanner_input_checks,
                    broker_getter(),
                    symbols=["BIRET", "DUMMYHEG", "HFCL"],
                    mode="swing",
                    period="2y",
                    strategy_id="tf_ema9_26_bullish_pivot",
                )
                app.state.scanner_input_probe = report
                LOG.warning(
                    "scanner_input_master count=%s reference_reliance_present=%s",
                    report.get("instrument_count", 0),
                    str(report.get("reference_reliance_present", False)).lower(),
                )
                for row in report["checks"]:
                    LOG.warning(
                        "scanner_input_probe symbol=%s code=%s candles=%s "
                        "orders_submitted=0",
                        row["symbol"],
                        row.get("error_code") or "inputs_available",
                        row.get("completed_candles", 0),
                    )
            except Exception:
                LOG.warning(
                    "scanner_input_probe code=probe_unavailable orders_submitted=0"
                )

    return asyncio.create_task(probe(), name="kite-read-only-session-probe")


async def stop_session_probe(task) -> None:
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
