"""Read-only evidence for a future manual Kite order workflow."""

import math
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from providers.kite_diagnostics import session_failure
from providers.kite_paper_quotes import FreshKitePaperQuotes


def kite_trading_readiness(
    broker, *, probe_quotes: bool = False, probe_history: bool = False, now=None
) -> dict:
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
    history = "not_probed"
    indicator_status = "not_probed"
    history_count = None
    if probe_history and authenticated:
        try:
            from indicators.indicator_engine import IndicatorEngine
            from providers.market_data_adapter import MarketDataAdapter
            from scanner.strategy_registry import list_strategies
            from services.technical_trading_service import TechnicalTradingService

            frame = broker.candles("RELIANCE", period="30d", interval="15m")
            frame = MarketDataAdapter._normalize("RELIANCE", frame)
            frame = TechnicalTradingService._completed_bars(
                frame, interval="15m", now=current
            )
            if not isinstance(frame, pd.DataFrame) or len(frame) < 30:
                raise ValueError("Insufficient completed historical candles")
            calculated = IndicatorEngine().calculate(frame)
            row = calculated.iloc[-1]
            required = {
                key
                for strategy in list_strategies(mode="intraday")
                if strategy["paper_eligible"]
                for key in strategy["indicators"]
            }
            if not all(math.isfinite(float(row.get(key))) for key in required):
                raise ValueError("Historical indicators are incomplete")
            history, indicator_status, history_count = (
                "available",
                "calculated",
                len(frame),
            )
        except Exception:
            history, indicator_status = "unavailable_or_invalid", "unavailable"
    checks = [
        {
            "check": "Authenticated Kite session",
            "status": "passed" if authenticated else "blocked",
        },
        {"check": "Fresh market quote", "status": quotes},
        {"check": "Completed historical candles", "status": history},
        {"check": "Scanner indicator calculation", "status": indicator_status},
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
        "history_status": history,
        "indicator_status": indicator_status,
        "history_completed_candles": history_count,
        "broker_write_opt_in_configured": configured,
        "broker_orders_allowed": False,
        "orders_submitted": 0,
        "checks": checks,
        "diagnostic": diagnostic,
        "notes": "Read-only preparation. Session authentication and "
        "broker write flags do not approve an order.",
    }
