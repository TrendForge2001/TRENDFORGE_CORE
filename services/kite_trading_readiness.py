"""Read-only evidence for a future manual Kite order workflow."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from providers.kite_diagnostics import session_failure
from providers.kite_paper_quotes import FreshKitePaperQuotes


def kite_trading_readiness(broker, *, probe_quotes: bool = False, now=None) -> dict:
    zone = ZoneInfo("Asia/Kolkata")
    current = now or datetime.now(zone)
    current = (
        current.replace(tzinfo=zone)
        if current.tzinfo is None
        else current.astimezone(zone)
    )
    try:
        health = broker.health()
        authenticated = isinstance(health, dict) and health.get("authenticated") is True
    except Exception as exc:
        authenticated = False
        diagnostic = session_failure(exc)
    else:
        from providers.kite_diagnostics import safe_session_failure

        diagnostic = (
            safe_session_failure(health if isinstance(health, dict) else {})
            if not authenticated
            else None
        )
    runtime = os.getenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    configured = getattr(broker, "live_trading_enabled", False) is True and runtime
    quotes = "not_probed"
    if probe_quotes and authenticated:
        try:
            FreshKitePaperQuotes(broker).prices(["NSE:RELIANCE"], now=current)
            quotes = "fresh"
        except Exception:
            quotes = "unavailable_or_stale"
    checks = [
        {
            "check": "Authenticated Kite session",
            "status": "passed" if authenticated else "blocked",
        },
        {"check": "Fresh market quote", "status": quotes},
        {
            "check": "Broker write opt-in configured",
            "status": "configured" if configured else "off",
        },
        {
            "check": "Manual order preview and risk limits",
            "status": "pending_implementation",
        },
        {
            "check": "Operator confirmation and duplicate-order protection",
            "status": "pending_implementation",
        },
        {
            "check": "Broker order/fill reconciliation and audit trail",
            "status": "pending_implementation",
        },
    ]
    return {
        "status": "preparation_only",
        "checked_at": current.isoformat(),
        "authenticated": authenticated,
        "quote_status": quotes,
        "broker_write_opt_in_configured": configured,
        "broker_orders_allowed": False,
        "orders_submitted": 0,
        "checks": checks,
        "diagnostic": diagnostic,
        "notes": "Read-only preparation. Session authentication and "
        "broker write flags do not approve an order.",
    }
