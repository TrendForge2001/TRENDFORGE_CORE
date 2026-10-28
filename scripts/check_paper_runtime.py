"""Read-only diagnosis of the running PC backend; never starts trading."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from scanner.strategy_registry import REGISTRY_VERSION


def diagnose(root: Path, *, port: int = 10000, session=None, now=None) -> dict:
    zone = ZoneInfo("Asia/Kolkata")
    current = now or datetime.now(zone)
    current = (
        current.replace(tzinfo=zone)
        if current.tzinfo is None
        else current.astimezone(zone)
    )
    report = {"checked_at": current.isoformat(), "read_only": True}
    if type(port) is not int or not 1024 <= port <= 65535:
        return {**report, "status": "invalid_port"}
    try:
        key = (
            (root / "private" / "admin-key.txt").read_text(encoding="utf-8-sig").strip()
        )
        if len(key) < 32:
            raise ValueError("Invalid administrative key")
    except (OSError, ValueError):
        return {**report, "status": "admin_key_unavailable"}

    client = session or requests.Session()
    # Local credentials must never travel through a configured network proxy.
    client.trust_env = False
    data = {}
    paths = {
        "automation": "/paper/automation",
        "paper": "/paper/readiness",
        "strategy_monitor": "/paper/strategy-monitor/readiness",
        "validation": "/technical/multi-strategy/validation/status",
        "kite": (
            "/workspace/kite-trading-readiness?probe_quotes=true&probe_history=true"
        ),
    }
    try:
        for name, path in paths.items():
            response = client.get(
                f"http://127.0.0.1:{port}{path}",
                headers={"X-TrendForge-Admin-Key": key},
                timeout=20,
                allow_redirects=False,
            )
            if response.status_code != 200:
                return {
                    **report,
                    "status": "backend_check_failed",
                    "failed_check": name,
                    "http_status": response.status_code,
                }
            data[name] = response.json()
            if not isinstance(data[name], dict):
                raise ValueError("Invalid status response")
    except (requests.RequestException, ValueError, TypeError):
        return {**report, "status": "backend_unavailable_or_invalid"}
    finally:
        if session is None:
            client.close()

    try:
        auto, paper, kite = data["automation"], data["paper"], data["kite"]
        storage = paper.get("entry_storage_policy") or {}
        monitor = paper.get("automatic_monitor") or {}
        validation = data["validation"]
        request = validation.get("request") or {}
        validation_ready = (
            validation.get("status") == "completed"
            and validation.get("registry_version") == REGISTRY_VERSION
            and "NIFTY 500" in request.get("universes", [])
            and request.get("source") == "all"
            and set(request.get("modes", [])) >= {"intraday", "swing", "positional"}
            and not request.get("limit")
            and not request.get("strategy_ids")
            and bool(validation.get("run_id"))
        )
        market_window = current.weekday() < 5 and time(9, 30) <= current.time() < time(
            14, 45
        )
        try:
            checked = datetime.fromisoformat(auto.get("last_checked_at") or "")
            age = (current - checked).total_seconds()
            heartbeat = 0 <= age <= 90
        except (TypeError, ValueError):
            heartbeat = False
        checks = {
            "valid_automation_control": type(auto.get("enabled")) is bool,
            "nifty500_scope": auto.get("universe") == "NIFTY 500",
            "settings_saved": auto.get("settings_saved") is True,
            "storage_verified": (
                storage.get("mode") == "durable"
                and storage.get("verified_persistent") is True
                and storage.get("entry_allowed") is True
            ),
            "paper_runtime_ready": paper.get("can_open_new_positions") is True,
            "kill_switch_off": paper.get("kill_switch") is False,
            "automation_worker_running": auto.get("worker_running") is True,
            "automation_heartbeat_recent": heartbeat,
            "quote_monitor_running": (
                monitor.get("enabled") is True and monitor.get("running") is True
            ),
            "strategy_monitor_enabled": data["strategy_monitor"].get("enabled") is True,
            "no_quote_monitor_error": not monitor.get("last_error"),
            "no_strategy_monitor_error": not data["strategy_monitor"].get("last_error"),
            "kite_authenticated": kite.get("authenticated") is True,
            "kite_historical_candles_available": kite.get("history_status")
            == "available",
            "scanner_indicators_calculated": kite.get("indicator_status")
            == "calculated",
            "no_automation_error": not auto.get("last_error"),
            "no_entry_blockers": auto.get("blockers") == [],
            "paper_only": (
                auto.get("paper_only") is True
                and auto.get("broker_orders_allowed") is False
                and paper.get("broker_orders_allowed") is False
                and kite.get("broker_orders_allowed") is False
            ),
        }
        if market_window and auto.get("enabled") is True:
            checks["fresh_market_quote"] = kite.get("quote_status") == "fresh"
            checks["nifty500_validation_complete"] = validation_ready
        issues = [name for name, passed in checks.items() if not passed]
        return {
            **report,
            "status": "needs_attention"
            if issues
            else "off"
            if auto.get("enabled") is not True
            else "waiting_for_market"
            if not market_window
            else "running",
            "checks": checks,
            "issues": issues,
            "automation_enabled": auto.get("enabled") is True,
            "phase": auto.get("phase"),
            "universe": auto.get("universe"),
            "target_symbols": auto.get("target_symbols"),
            "target_strategy_ids": auto.get("target_strategy_ids"),
            "last_checked_at": auto.get("last_checked_at"),
            "cycle_in_progress": auto.get("busy") is True,
            "validation_complete": validation_ready,
            "quote_status": kite.get("quote_status"),
            "history_status": kite.get("history_status"),
            "indicator_status": kite.get("indicator_status"),
            "market_entry_window_open": market_window,
            "note": "A running worker does not prove a fill. Strategy validation, "
            "current signals, exchange holidays and per-trade risk checks still apply.",
        }
    except (AttributeError, TypeError, ValueError):
        return {**report, "status": "backend_unavailable_or_invalid"}


def main(argv: list[str] | None = None) -> int:
    root = (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        / "TrendForgeCore"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=root)
    parser.add_argument("--port", type=int, default=10000)
    args = parser.parse_args(argv)
    report = diagnose(args.data_dir, port=args.port)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] in {"running", "off", "waiting_for_market"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
