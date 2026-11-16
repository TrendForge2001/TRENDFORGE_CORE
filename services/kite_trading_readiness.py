"""Read-only evidence for a future manual Kite order workflow."""

import math
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from providers.kite_diagnostics import session_failure
from providers.kite_errors import NetworkException, PermissionException, TokenException
from providers.kite_paper_quotes import FreshKitePaperQuotes


def required_intraday_indicators():
    from scanner.strategy_registry import list_strategies

    return {
        key
        for strategy in list_strategies(mode="intraday")
        if strategy["paper_eligible"]
        for key in strategy["indicators"]
        if not key.startswith("TRAD_") or key.startswith("TRAD_DAY_")
    }


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
    history_diagnostic = None
    missing_indicators = []
    session_counts = []
    if probe_history and authenticated:
        stage, failure_code = "history_request", None
        try:
            from indicators.indicator_engine import IndicatorEngine
            from providers.market_data_adapter import MarketDataAdapter
            from services.technical_trading_service import TechnicalTradingService

            frame = broker.candles("RELIANCE", period="30d", interval="15m")
            stage = "normalization"
            frame = MarketDataAdapter._normalize("RELIANCE", frame)
            stage = "completed_bars"
            frame = TechnicalTradingService._completed_bars(
                frame, interval="15m", now=current
            )
            history_count = len(frame) if isinstance(frame, pd.DataFrame) else None
            if history_count is None or history_count < 30:
                failure_code = "insufficient_completed_candles"
                raise ValueError("Insufficient completed historical candles")
            history = "available"
            stage = "indicators"
            stamps = pd.DatetimeIndex(frame.index)
            stamps = (
                stamps.tz_localize(zone)
                if stamps.tz is None
                else stamps.tz_convert(zone)
            )
            for day in stamps.normalize().unique()[-2:]:
                observed = stamps[stamps.normalize() == day]
                minutes = observed.hour * 60 + observed.minute
                normal = (
                    (minutes >= 555) & (minutes <= 915) & ((minutes - 555) % 15 == 0)
                )
                session_counts.append(
                    {"normal": int(normal.sum()), "other": int((~normal).sum())}
                )
            calculated = IndicatorEngine().calculate(frame)
            row = calculated.iloc[-1]
            for key in sorted(required_intraday_indicators()):
                try:
                    finite = math.isfinite(float(row.get(key)))
                except (TypeError, ValueError, OverflowError):
                    finite = False
                if not finite:
                    missing_indicators.append(key)
            if missing_indicators:
                failure_code = "indicator_history_incomplete"
                raise ValueError("Historical indicators are incomplete")
            history, indicator_status, history_count = (
                "available",
                "calculated",
                len(frame),
            )
        except Exception as exc:
            if history != "available":
                history = "unavailable_or_invalid"
            indicator_status = "unavailable"
            if isinstance(exc, TokenException):
                failure_code = "history_authentication_failed"
            elif isinstance(exc, PermissionException):
                failure_code = "history_access_denied"
            elif isinstance(exc, NetworkException):
                failure_code = "history_transport_unavailable"
            history_diagnostic = {
                "stage": stage,
                "code": failure_code
                or {
                    "history_request": "history_request_failed",
                    "normalization": "invalid_history_payload",
                    "completed_bars": "invalid_completed_history",
                    "indicators": "indicator_calculation_failed",
                }[stage],
            }
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
            "check": "Read-only order preview",
            "status": "available_requires_fresh_inputs",
        },
        {
            "check": "Live-money risk admission",
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
        "history_diagnostic": history_diagnostic,
        "history_missing_indicators": missing_indicators,
        "history_session_counts": session_counts,
        "broker_write_opt_in_configured": configured,
        "broker_orders_allowed": False,
        "orders_submitted": 0,
        "checks": checks,
        "diagnostic": diagnostic,
        "notes": "Read-only preparation. Session authentication and "
        "broker write flags do not approve an order.",
    }
