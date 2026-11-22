"""Opt-in, one-use Render paper command. Normal restarts still leave entries OFF.

The private environment request is an operator action, not a boot preference.
Its durable claim is consumed before validation and can never resume after a
restart. This module has no broker order submission capability.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
from datetime import UTC, datetime, time

from core.deployment_role import cloud_read_only, on_render
from scanner.strategy_registry import REGISTRY_VERSION
from scanner.strategy_scope import active_modes
from services.paper_startup_probe import paper_session_probe
from services.trading_calendar import latest_completed_session

ENV = "TRENDFORGE_PAPER_OPERATOR_REQUEST"
LOG = logging.getLogger("trendforge.paper.operator")
MODES = {"intraday", "swing", "positional"}
DEFERRED = {
    "current_scope_validation_complete",
    "validated_strategy_pair_available",
    "entry_window_open",
    "fresh_market_quote",
    "recent_worker_heartbeat",
}
BASE_CHECKS = {
    "authenticated_reads",
    "kite_authenticated",
    "completed_history_available",
    "scanner_indicators_calculated",
    "storage_verified",
    "paper_runtime_ready",
    "kill_switch_off",
    "automation_worker_running",
    "quote_exit_monitor_running",
    "strategy_exit_monitor_enabled",
    "monitors_without_error",
    "no_entry_blockers",
    "automation_settings_saved",
    "automation_without_error",
    "paper_only",
}
HISTORICAL_CHECKS = {
    "authenticated_reads",
    "kite_authenticated",
    "completed_history_available",
    "scanner_indicators_calculated",
    "storage_verified",
    "paper_only",
}


def _all_ready(checks, *, research=False):
    required = BASE_CHECKS | DEFERRED
    if research:
        required = required - {"validated_strategy_pair_available"}
    return checks.keys() >= required and all(
        value is True
        for key, value in checks.items()
        if not research or key != "validated_strategy_pair_available"
    )


def _timestamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result


def _request(raw, now):
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {
        "id",
        "action",
        "registry_version",
        "authorized_at",
        "expires_at",
        "confirm_render_executor",
    }:
        raise ValueError("Invalid command")
    if (
        not isinstance(value["id"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", value["id"])
        or value["action"]
        not in {
            "validate_then_start",
            "review_validation",
            "retry_failed_validation",
            "run_corrected_research",
            "recover_corrected_research",
            "start_research_paper",
        }
        or value["registry_version"] != REGISTRY_VERSION
        or value["confirm_render_executor"] is not True
    ):
        raise ValueError("Invalid command")
    authorized, expires = map(_timestamp, (value["authorized_at"], value["expires_at"]))
    if (
        not authorized <= now < expires
        or not 0 < (expires - authorized).total_seconds() <= 86400
    ):
        raise ValueError("Expired or invalid authorization")
    return value


def _scope(auto):
    return {
        "universe": auto["universe"],
        "symbols": auto.get("target_symbols"),
        "strategy_ids": auto.get("target_strategy_ids"),
        "assume_short_borrow": auto.get("assume_short_borrow", False),
    }


def _matches(validation, request):
    actual = validation.get("request") or {}
    return (
        set(actual.get("universes") or []) == set(request["universes"])
        and set(actual.get("modes") or []) == set(active_modes())
        and actual.get("source") == "all"
        and actual.get("limit") is None
        and actual.get("strategy_ids") is None
        and actual.get("capital", 100_000.0) == request["capital"]
    )


async def run_paper_operator_request(
    raw,
    *,
    automation_getter,
    validation_getter,
    validation_starter,
    readiness=paper_session_probe,
    clock=lambda: datetime.now(UTC),
    sleep=asyncio.sleep,
):
    """Validate and issue Start at most once, preserving saved scope and limits."""
    receipt, repository, key = {}, None, None

    def record(phase, **details):
        receipt.update(phase=phase, checked_at=clock().isoformat(), **details)
        repository.save_state(key, "paper_operator_request", receipt)
        # Receipt contains fixed diagnostic fields only, never account/provider data.
        LOG.warning("paper_operator_request %s", json.dumps(receipt, sort_keys=True))

    try:
        command = _request(raw, clock())
        if (
            not on_render()
            or cloud_read_only()
            or os.getenv("TRENDFORGE_CLOUD_PAPER_EXECUTION", "").lower() != "true"
        ):
            raise ValueError("Render paper execution required")
        automation = automation_getter()
        auto = automation.status()
        scope = _scope(auto)
        generation = auto["control_generation"]
        capital = auto.get("account_policy", {}).get("capital", 100_000.0)
        if (
            scope["universe"] not in {"NIFTY 100", "NIFTY 200", "NIFTY 500"}
            or type(capital) not in (float, int)
            or not math.isfinite(capital)
            or not 1_000 <= capital <= 1_000_000_000
            or auto.get("paper_only") is not True
            or auto.get("broker_orders_allowed") is not False
        ):
            raise ValueError("Invalid saved paper scope")
        repository = automation.repository
        key = "paper.operator:" + command["id"]
        request_hash = hashlib.sha256(raw.encode()).hexdigest()
        # Never re-arm a consumed request, including one interrupted by a restart.
        existing = repository.load_state(key)
        if existing:
            LOG.warning("paper_operator_request phase=already_consumed replay=false")
            return
        saved = repository.load_state(automation.CONFIG_KEY)
        updated = (saved or {}).get("payload", {}).get("updated_at")
        if updated and _timestamp(updated) > _timestamp(command["authorized_at"]):
            raise ValueError("Newer manual paper control")
        report = await asyncio.to_thread(readiness)
        checks = report.get("checks") or {}
        if checks.get("storage_verified") is not True:
            raise ValueError("Verified paper storage required")
        receipt = {
            "request_id": command["id"],
            "request_hash": request_hash,
            "phase": "claimed",
            "checked_at": clock().isoformat(),
            "universe": scope["universe"],
            "target_stock_count": len(scope["symbols"]) if scope["symbols"] else None,
            "target_strategy_count": len(scope["strategy_ids"])
            if scope["strategy_ids"]
            else None,
            "broker_orders_allowed": False,
        }
        if not repository.claim_state(key, "paper_operator_request", receipt):
            LOG.warning("paper_operator_request phase=already_consumed replay=false")
            return
        if auto.get("enabled") is True:
            record("already_enabled", automation_enabled=True)
            return
        request = {
            "universes": [scope["universe"]],
            "modes": sorted(active_modes()),
            "source": "all",
            "strategy_ids": None,
            "limit": None,
            "capital": capital,
            "chunk_size": 5,
            "force_refresh_universes": False,
        }
        run_id, attempted = None, False
        record("preflight")
        if command["action"] == "start_research_paper":
            from services import paper_research_policy as research

            policy = research.create(
                automation.bridge.paper_auto_entry,
                validation_getter(),
                universe=scope["universe"],
                symbols=scope["symbols"],
                strategy_ids=scope["strategy_ids"],
                now=clock(),
            )
            while clock() < _timestamp(command["expires_at"]):
                current = automation.status()
                if (
                    current["control_generation"] != generation
                    or _scope(current) != scope
                    or current.get("enabled") is True
                    or not research.current(
                        policy, automation.bridge.paper_auto_entry, validation_getter()
                    )
                ):
                    record("superseded")
                    return
                critical = sorted(
                    name for name in BASE_CHECKS if checks.get(name) is not True
                )
                if critical:
                    record("blocked", failed_checks=critical)
                    return
                if _all_ready(checks, research=True):
                    record(
                        "research_start_requested",
                        research_strategy_pairs=len(policy["strategy_pairs"]),
                    )
                    automation.configure(
                        True,
                        **scope,
                        admission_mode="research",
                        confirm_render_executor=True,
                        expected_control_generation=generation,
                    )
                    await sleep(16)
                    result = await asyncio.to_thread(readiness)
                    current = automation.status()
                    started = (
                        current.get("enabled") is True
                        and current.get("admission_mode") == "research"
                        and current.get("research_policy_current") is True
                        and current["control_generation"] == generation + 1
                        and _scope(current) == scope
                        and _all_ready(result.get("checks") or {}, research=True)
                    )
                    record(
                        "started_research"
                        if started
                        else "research_start_needs_attention",
                        automation_enabled=current.get("enabled") is True,
                        admission_mode=current.get("admission_mode"),
                        research_policy_id=(current.get("research_policy") or {}).get(
                            "policy_id"
                        ),
                        research_strategy_pairs=len(policy["strategy_pairs"]),
                        eligible_strategy_pairs=result.get(
                            "eligible_strategy_pairs", 0
                        ),
                        failed_checks=result.get("failed_checks", []),
                        broker_orders_created=0,
                    )
                    return
                record(
                    "awaiting_research_ready",
                    failed_checks=[
                        key
                        for key, value in checks.items()
                        if value is not True
                        and key != "validated_strategy_pair_available"
                    ],
                )
                await sleep(30)
                report = await asyncio.to_thread(readiness)
                checks = report.get("checks") or {}
            record("expired")
            return
        if command["action"] == "recover_corrected_research":
            from services.paper_admission_policy import capture, fingerprint
            from services.validation_journal import ValidationJournal

            critical = sorted(
                name for name in BASE_CHECKS if checks.get(name) is not True
            )
            snapshot = validation_getter()
            saved = snapshot.get("request") or {}
            policy = capture(automation.bridge.paper_auto_entry)
            if (
                critical
                or snapshot.get("status") not in {"failed", "interrupted"}
                or snapshot.get("worker_alive") is True
                or snapshot.get("registry_version") != REGISTRY_VERSION
                or not snapshot.get("checkpointed")
                or not ValidationJournal.recent(snapshot.get("as_of"))
                or not _matches(snapshot, request)
                or saved.get("shared_book") is not True
                or saved.get("assume_short_borrow") != scope["assume_short_borrow"]
                or saved.get("admission_policy") != policy
            ):
                record(
                    "research_recovery_blocked",
                    failed_checks=critical,
                    paper_entries_changed=False,
                )
                return
            result = validation_starter({**saved, "compact_checkpoints": True})
            record(
                "corrected_research_recovery_requested",
                run_id=result.get("run_id"),
                admission_policy_hash=fingerprint(policy),
                validation_status=result.get("status"),
                preserved_processed_symbol_modes=(snapshot.get("progress") or {}).get(
                    "processed_symbol_modes"
                ),
                paper_entries_changed=False,
            )
            return
        if command["action"] == "run_corrected_research":
            from zoneinfo import ZoneInfo

            from services.paper_admission_policy import capture, fingerprint

            # Historical reads preserve the saved admission policy. They do not
            # need an open market, a fresh LTP, or free paper-position slots.
            # Entry/monitor guards remain mandatory for every paper Start path.
            critical = sorted(
                name for name in HISTORICAL_CHECKS if checks.get(name) is not True
            )
            if critical or auto.get("enabled") is True:
                record(
                    "blocked",
                    failed_checks=critical or ["paper_entries_must_remain_off"],
                )
                return
            policy = capture(automation.bridge.paper_auto_entry)
            if policy["capital"] != 100_000:
                record("research_scope_mismatch", paper_entries_changed=False)
                return
            end = datetime.combine(
                latest_completed_session(clock()),
                time(15, 30),
                ZoneInfo("Asia/Kolkata"),
            )
            corrected = {
                **request,
                "universes": ["NIFTY 500"],
                "force": True,
                "force_refresh_universes": True,
                "admission_policy": policy,
                "shared_book": True,
                "assume_short_borrow": scope["assume_short_borrow"],
                "evaluation_as_of": end.isoformat(),
            }
            LOG.warning(
                "corrected_research_policy %s",
                json.dumps(
                    {
                        "policy": policy,
                        "policy_hash": fingerprint(policy),
                        "evaluation_as_of": end.isoformat(),
                        "short_borrow_assumed": scope["assume_short_borrow"],
                        "paper_entries_changed": False,
                    },
                    sort_keys=True,
                ),
            )
            result = validation_starter(corrected)
            record(
                "corrected_research_requested",
                validation_status=result.get("status"),
                admission_policy_hash=fingerprint(policy),
                paper_entries_changed=False,
            )
            return
        if command["action"] == "retry_failed_validation":
            snapshot = validation_getter()
            critical = sorted(
                name for name in BASE_CHECKS if checks.get(name) is not True
            )
            if critical:
                record("blocked", failed_checks=critical)
                return
            if (
                snapshot.get("status") != "completed"
                or snapshot.get("registry_version") != REGISTRY_VERSION
                or not _matches(snapshot, request)
                or not snapshot.get("checkpointed")
                or not snapshot.get("error_count")
            ):
                record("retry_rejected")
                return
            result = validation_starter({**snapshot["request"], "retry_failed": True})
            record(
                "retry_requested",
                validation_status=result.get("status"),
                paper_entries_changed=False,
            )
            return
        if command["action"] == "review_validation":
            from services.validation_review import error_diagnostics, validation_review
            from services.validation_trade_diagnostics import trade_diagnostics

            # This branch can only inspect saved evidence and loopback readiness.
            # It never calls validation_starter or automation.configure.
            snapshot = validation_getter()
            review = validation_review(snapshot, scope["universe"])
            review["failure_diagnostics"] = error_diagnostics(snapshot)
            for row in review.pop("rows"):
                LOG.warning(
                    "validation_review_strategy %s", json.dumps(row, sort_keys=True)
                )
            diagnostics = await asyncio.to_thread(
                trade_diagnostics, snapshot, scope["universe"]
            )
            review["trade_diagnostics_status"] = diagnostics["status"]
            for row in diagnostics["rows"]:
                LOG.warning(
                    "validation_trade_diagnostics %s", json.dumps(row, sort_keys=True)
                )
            LOG.warning(
                "paper_session_readiness %s", json.dumps(report, sort_keys=True)
            )
            record(
                "reviewed",
                review=review,
                failed_checks=report.get("failed_checks", []),
                eligible_strategy_pairs=report.get("eligible_strategy_pairs", 0),
                automation_enabled=auto.get("enabled") is True,
            )
            return
        while clock() < _timestamp(command["expires_at"]):
            auto = automation.status()
            if (
                auto["control_generation"] != generation
                or _scope(auto) != scope
                or auto.get("account_policy", {}).get("capital", 100_000.0) != capital
            ):
                record("superseded")
                return
            if auto.get("enabled") is True:
                record("superseded")
                return
            # Any base safety failure terminates the request. Market opening,
            # a fresh quote and first heartbeat may be awaited while entries OFF.
            failed = [name for name, passed in checks.items() if passed is not True]
            critical = sorted((BASE_CHECKS - checks.keys()) | (set(failed) - DEFERRED))
            if not checks or critical:
                record("blocked", failed_checks=critical or ["readiness_unavailable"])
                return
            validation = validation_getter()
            matched = _matches(validation, request)
            if (
                validation.get("status") == "completed"
                and matched
                and validation.get("registry_version") == REGISTRY_VERSION
            ):
                report = await asyncio.to_thread(readiness)
                checks = report.get("checks") or {}
                if checks.get("validated_strategy_pair_available") is not True:
                    record("validation_rejected", eligible_strategy_pairs=0)
                    return
                if _all_ready(checks):
                    # There are no suspension points between final CAS and Start.
                    # Stop during long validation/waiting always supersedes this.
                    if clock() >= _timestamp(command["expires_at"]):
                        break
                    if (
                        automation.status()
                        .get("account_policy", {})
                        .get("capital", 100_000.0)
                        != capital
                    ):
                        record("superseded")
                        return
                    record(
                        "start_requested",
                        eligible_strategy_pairs=report["eligible_strategy_pairs"],
                    )
                    automation.configure(
                        True,
                        **scope,
                        confirm_render_executor=True,
                        expected_control_generation=generation,
                    )
                    await sleep(16)
                    result = await asyncio.to_thread(readiness)
                    current = automation.status()
                    if (
                        current.get("enabled") is True
                        and current["control_generation"] == generation + 1
                        and _scope(current) == scope
                        and result.get("automation_enabled") is True
                        and _all_ready(result.get("checks") or {})
                    ):
                        record(
                            "started",
                            automation_enabled=True,
                            worker_running=True,
                            eligible_strategy_pairs=result["eligible_strategy_pairs"],
                        )
                    else:
                        record(
                            "start_needs_attention",
                            automation_enabled=current.get("enabled") is True,
                            failed_checks=result.get("failed_checks", []),
                        )
                    return
                record("awaiting_ready", failed_checks=report.get("failed_checks", []))
            elif validation.get("status") in {"running", "starting"}:
                if run_id and validation.get("run_id") != run_id:
                    record("validation_superseded")
                    return
                if matched:
                    run_id = validation.get("run_id")
                progress = validation.get("progress") or {}
                pct = progress.get("progress_pct")
                processed = progress.get("processed_symbol_modes", 0)
                total = progress.get("total_symbol_modes", 0)
                if type(pct) not in (float, int):
                    pct = (
                        round(100 * processed / total, 2)
                        if type(processed) is int and type(total) is int and total > 0
                        else receipt.get("progress_pct", 0)
                    )
                record(
                    "validating",
                    progress_pct=pct,
                    validation_mode=progress.get("mode")
                    if progress.get("mode") in MODES
                    else "unknown",
                    processed_symbol_modes=processed if type(processed) is int else 0,
                    total_symbol_modes=total if type(total) is int else 0,
                )
            elif attempted:
                record("validation_failed")
                return
            else:
                # Existing workload admission and provider/strategy validation
                # enforce their normal limits; no forced pass or cancel.
                result = validation_starter(request)
                attempted = True
                run_id = result.get("run_id")
                record("validation_requested")
            await sleep(30)
        record("expired")
    except asyncio.CancelledError:
        if receipt:
            record("interrupted")
        raise
    except Exception:  # noqa: BLE001 - provider errors may contain private data
        # Exceptions may contain private broker/account details; publish no text.
        if receipt:
            try:
                record("failed")
            except Exception:  # noqa: BLE001 - fail closed on receipt storage errors
                LOG.warning("paper_operator_request phase=receipt_storage_failed")
        else:
            LOG.warning("paper_operator_request phase=rejected")


def start_paper_operator_request(**callbacks):
    raw = os.getenv(ENV, "")
    if not raw:
        return None

    async def deferred():
        # Wait until the ASGI server can answer its private loopback diagnostics.
        await asyncio.sleep(2)
        await run_paper_operator_request(raw, **callbacks)

    return asyncio.create_task(deferred(), name="one-use-paper-operator-request")
