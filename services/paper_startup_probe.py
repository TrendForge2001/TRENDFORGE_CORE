"""Private, read-only paper readiness evidence from the running server."""

from __future__ import annotations

import json
import math
import os
import urllib.request
from datetime import datetime, time
from zoneinfo import ZoneInfo

from scanner.multi_strategy_engine import REVIEW_REQUIRED
from scanner.strategy_registry import REGISTRY_VERSION, list_strategies
from services.kite_trading_readiness import required_intraday_indicators

PATHS = {
    "automation": "/paper/automation",
    "paper": "/paper/readiness",
    "strategy_monitor": "/paper/strategy-monitor/readiness",
    "validation": "/technical/multi-strategy/validation/status",
    "kite": "/workspace/kite-trading-readiness?probe_quotes=true&probe_history=true",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _state(value, allowed):
    return value if isinstance(value, str) and value in allowed else "unknown"


def _validation_diagnostics(validation, universe):
    """Counts and fixed gate names only; never emit private report/error text."""
    definitions = {row["strategy_id"]: row for row in list_strategies()}
    known_checks = {
        "minimum_completed_symbols",
        "minimum_total_trades",
        "minimum_universe_scope",
        "coverage",
        "positive_net_pnl",
        "profitable_symbol_pct",
        "profit_factor",
        "median_symbol_return",
        "average_drawdown",
        "worst_drawdown",
    }
    metrics = validation.get("strategy_universe_metrics")
    metrics = metrics if isinstance(metrics, list) else []
    modes = []
    for mode in ("intraday", "swing", "positional"):
        rows = [
            row
            for row in metrics
            if isinstance(row, dict)
            and row.get("universe") == universe
            and row.get("mode") == mode
            and isinstance(row.get("strategy_id"), str)
            and row["strategy_id"] in definitions
        ]
        failures, statuses, coverage, completed = {}, {}, [], []
        passed_directions = {"LONG": 0, "SHORT": 0}
        for row in rows:
            gate = _mapping(row.get("validation_gate"))
            status = _state(gate.get("status"), {"PASS", "FAIL", "INSUFFICIENT_DATA"})
            statuses[status] = statuses.get(status, 0) + 1
            if status == "PASS":
                direction = definitions[row["strategy_id"]].get("direction", "LONG")
                if direction in passed_directions:
                    passed_directions[direction] += 1
            for name, passed in _mapping(gate.get("checks")).items():
                if name in known_checks and passed is False:
                    failures[name] = failures.get(name, 0) + 1
            value = row.get("coverage_pct")
            if (
                type(value) in (int, float)
                and math.isfinite(value)
                and 0 <= value <= 100
            ):
                coverage.append(round(value, 2))
            value = row.get("completed_symbols")
            if type(value) is int and 0 <= value <= 10000:
                completed.append(value)
        modes.append(
            {
                "mode": mode,
                "strategy_pairs": len(rows),
                "registry_paper_eligible_pairs": sum(
                    row.get("registry_paper_eligible") is True for row in rows
                ),
                "passed_directions": passed_directions,
                "gate_status_counts": statuses,
                "failed_check_counts": failures,
                "minimum_coverage_pct": min(coverage) if coverage else None,
                "maximum_coverage_pct": max(coverage) if coverage else None,
                "maximum_completed_symbols": max(completed) if completed else None,
            }
        )
    return {
        "master_symbol_count": validation.get("master_symbol_count")
        if type(validation.get("master_symbol_count")) is int
        else None,
        "backtest_error_count": validation.get("error_count")
        if type(validation.get("error_count")) is int
        else None,
        "registry_current": validation.get("registry_version") == REGISTRY_VERSION,
        "modes": modes,
    }


def paper_session_probe(*, opener=None, now=None):
    """GET loopback diagnostics; return only fixed checks, never private payloads."""
    current = now or datetime.now(ZoneInfo("Asia/Kolkata"))
    current = (
        current.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        if current.tzinfo is None
        else current.astimezone(ZoneInfo("Asia/Kolkata"))
    )
    report = {
        "checked_at": current.isoformat(),
        "read_only": True,
        "automation_changed": False,
        "probe_orders_submitted": 0,
        "candidate_risk_admission": "required_before_every_fill",
        "market_data_probe_scope": "NSE:RELIANCE / 15-minute candles",
    }
    key = os.getenv("TRENDFORGE_ADMIN_API_KEY", "").strip()
    if len(key) < 32:
        return {**report, "status": "admin_key_unavailable"}
    try:
        port = int(os.getenv("PORT", "10000"))
        if not 1024 <= port <= 65535:
            raise ValueError("Invalid loopback port")
    except ValueError:
        return {**report, "status": "invalid_port"}
    client = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect()
    )
    data, failed = {}, []
    for name, path in PATHS.items():
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            headers={"X-TrendForge-Admin-Key": key, "Accept": "application/json"},
            method="GET",
        )
        try:
            with client.open(request, timeout=20) as response:
                raw = response.read(2_000_001)
                if response.status != 200 or len(raw) > 2_000_000:
                    raise ValueError("Invalid diagnostic response")
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise ValueError("Invalid diagnostic payload")
                data[name] = body
        except (OSError, ValueError, TypeError):
            failed.append(name)
    if now is None:
        current = datetime.now(ZoneInfo("Asia/Kolkata"))
        report["checked_at"] = current.isoformat()
    auto, paper, kite = (data.get(name, {}) for name in ("automation", "paper", "kite"))
    validation = data.get("validation", {})
    monitor = _mapping(paper.get("automatic_monitor"))
    strategy_monitor = data.get("strategy_monitor", {})
    storage = _mapping(paper.get("entry_storage_policy"))
    request = _mapping(validation.get("request"))
    universe = auto.get("universe")
    scope_valid = isinstance(universe, str) and universe in {
        "NIFTY 100",
        "NIFTY 200",
        "NIFTY 500",
    }
    modes, universes = request.get("modes"), request.get("universes")
    current_validation = (
        validation.get("status") == "completed"
        and validation.get("registry_version") == REGISTRY_VERSION
        and bool(validation.get("run_id"))
        and scope_valid
        and isinstance(universes, list)
        and universe in universes
        and isinstance(modes, list)
        and all(mode in modes for mode in ("intraday", "swing", "positional"))
        and request.get("source") == "all"
        and not request.get("limit")
        and not request.get("strategy_ids")
    )
    target_ids = auto.get("target_strategy_ids")
    allowed = {
        row["strategy_id"]
        for row in list_strategies()
        if row["paper_eligible"]
        and row["strategy_id"] not in REVIEW_REQUIRED
        and (row.get("direction") != "SHORT" or auto.get("assume_short_borrow") is True)
    }
    if isinstance(target_ids, list):
        allowed.intersection_update(
            value for value in target_ids if isinstance(value, str)
        )
    elif target_ids is not None:
        allowed.clear()
    rows = validation.get("strategy_validation")
    eligible = set()
    for row in rows if isinstance(rows, list) else []:
        row = _mapping(row)
        gates = row.get("universe_gates")
        strategy_id, mode = row.get("strategy_id"), row.get("mode")
        if (
            current_validation
            and isinstance(strategy_id, str)
            and strategy_id in allowed
            and isinstance(mode, str)
            and mode in {"intraday", "swing", "positional"}
            and row.get("registry_paper_eligible") is True
            and row.get("promotion_status") == "ELIGIBLE_FOR_REVIEW"
            and any(
                _mapping(gate).get("universe") == universe
                and _mapping(gate).get("status") == "PASS"
                for gate in (gates if isinstance(gates, list) else [])
            )
        ):
            eligible.add((strategy_id, mode))
    try:
        heartbeat_age = (
            current - datetime.fromisoformat(auto.get("last_checked_at") or "")
        ).total_seconds()
        recent_heartbeat = 0 <= heartbeat_age <= 90
    except (ValueError, TypeError):
        recent_heartbeat = False
    checks = {
        "authenticated_reads": not failed,
        "kite_authenticated": kite.get("authenticated") is True,
        "fresh_market_quote": kite.get("quote_status") == "fresh",
        "completed_history_available": kite.get("history_status") == "available",
        "scanner_indicators_calculated": kite.get("indicator_status") == "calculated",
        "storage_verified": storage.get("mode") == "durable"
        and storage.get("verified_persistent") is True
        and storage.get("entry_allowed") is True,
        "paper_runtime_ready": paper.get("can_open_new_positions") is True,
        "kill_switch_off": paper.get("kill_switch") is False,
        "automation_worker_running": auto.get("worker_running") is True,
        "recent_worker_heartbeat": recent_heartbeat,
        "quote_exit_monitor_running": monitor.get("enabled") is True
        and monitor.get("running") is True,
        "strategy_exit_monitor_enabled": strategy_monitor.get("enabled") is True,
        "monitors_without_error": not monitor.get("last_error")
        and not strategy_monitor.get("last_error"),
        "no_entry_blockers": auto.get("blockers") == [],
        "automation_settings_saved": auto.get("settings_saved") is True,
        "automation_without_error": not auto.get("last_error"),
        "current_scope_validation_complete": current_validation,
        "validated_strategy_pair_available": bool(eligible),
        "paper_only": auto.get("paper_only") is True
        and all(
            value.get("broker_orders_allowed") is False for value in (auto, paper, kite)
        ),
        "entry_window_open": current.weekday() < 5
        and time(9, 30) <= current.time() < time(14, 45),
    }
    required = required_intraday_indicators()
    missing = kite.get("history_missing_indicators")
    missing = (
        sorted({name for name in missing if isinstance(name, str) and name in required})
        if isinstance(missing, list)
        else []
    )
    session_counts = kite.get("history_session_counts")
    session_counts = (
        [
            {
                key: value[key]
                for key in ("normal", "other")
                if type(value.get(key)) is int and 0 <= value[key] <= 10000
            }
            for value in session_counts
            if isinstance(value, dict)
        ]
        if isinstance(session_counts, list)
        else []
    )
    return {
        **report,
        "status": "checks_passed" if all(checks.values()) else "needs_attention",
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "failed_reads": failed,
        "automation_enabled": auto.get("enabled") is True,
        "validation_status": _state(
            validation.get("status"),
            {"completed", "running", "starting", "failed", "not_started"},
        ),
        "eligible_strategy_pairs": len(eligible),
        "validation_diagnostics": _validation_diagnostics(validation, universe),
        "quote_status": _state(
            kite.get("quote_status"), {"fresh", "unavailable_or_stale", "not_probed"}
        ),
        "history_status": _state(
            kite.get("history_status"),
            {"available", "unavailable_or_invalid", "not_probed"},
        ),
        "history_completed_candles": kite.get("history_completed_candles")
        if type(kite.get("history_completed_candles")) is int
        else None,
        "history_missing_indicators": missing,
        "history_required_indicator_count": len(required),
        "history_pivot_reference_source": _state(
            kite.get("history_pivot_reference_source"),
            {
                "kite_completed_daily",
                "complete_intraday_sessions",
                "incomplete_intraday_session",
                "not_probed",
            },
        ),
        "history_session_counts": session_counts[-2:],
        "history_failure_stage": _state(
            _mapping(kite.get("history_diagnostic")).get("stage"),
            {"history_request", "normalization", "completed_bars", "indicators"},
        ),
        "history_failure_code": _state(
            _mapping(kite.get("history_diagnostic")).get("code"),
            {
                "history_authentication_failed",
                "history_access_denied",
                "history_transport_unavailable",
                "history_request_failed",
                "invalid_history_payload",
                "invalid_completed_history",
                "insufficient_completed_candles",
                "indicator_history_incomplete",
                "indicator_calculation_failed",
            },
        ),
    }
