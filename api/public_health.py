"""Allowlisted public health summary, separate from administrative diagnostics."""
from __future__ import annotations

from typing import Any


_STATUSES = frozenset({
    "healthy", "ok", "configured", "not_configured", "degraded", "partial",
    "unavailable", "failed", "ready", "not_ready", "disabled", "enabled",
    "unknown", "invalid", "not_initialized", "initialized", "runtime_verified",
    "not_probed", "not_supported", "running", "starting", "stopped", "idle",
    "locked", "blocked", "missing", "stale",
})


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _status(value: Any) -> str:
    return value if isinstance(value, str) and value in _STATUSES else "unknown"


def _component(value: Any) -> dict[str, str]:
    return {"status": _status(_mapping(value).get("status"))}


def public_health(report: Any) -> dict[str, Any]:
    """Return fixed component names and known states; never copy free-form text.

    Provider errors can be embedded in successful HTTP 200 diagnostics, including
    inside a ``status`` field. Explicitly validate state values as well as keys.
    """
    source = _mapping(report)
    result: dict[str, Any] = {"status": _status(source.get("status"))}
    for name in (
        "configuration", "database", "market_data", "enrichment",
        "enrichment_snapshot", "fundamental_import", "scanner",
    ):
        result[name] = _component(source.get(name))
    for name, children in (
        ("execution", ("paper_trading", "paper_quote_monitor", "paper_auto_entry")),
        ("observability", ("scan_run_audit", "scan_continuations")),
        ("universe", ("nifty500", "provider")),
    ):
        section = _mapping(source.get(name))
        result[name] = {child: _component(section.get(child)) for child in children}

    # Configuration flags help the dashboard distinguish a configured broker
    # from an authenticated one without revealing credentials or error text.
    configuration = _mapping(source.get("configuration"))
    for flag in ("kite_configured", "kite_authenticated"):
        if type(configuration.get(flag)) is bool:
            result["configuration"][flag] = configuration[flag]
    scanner = _mapping(source.get("scanner"))
    result["scanner"]["runtime_status"] = _status(scanner.get("runtime_status"))
    return result


__all__ = ["public_health"]
