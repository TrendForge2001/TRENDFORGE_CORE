"""Authenticated, read-only market preparation; never submit broker orders."""

import logging
import math
import re
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from providers.kite_paper_quotes import FreshKitePaperQuotes

TZ = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)


class PreflightInputError(ValueError):
    """Fixed, safe operator-facing validation failure."""


def _symbol(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Z0-9][A-Z0-9._&-]{0,29}", value)
        or ".." in value
    ):
        raise PreflightInputError("Choose an NSE equity symbol")
    return value


def _instruments(broker):
    rows = broker.instruments("NSE")
    LOG.warning(
        "instrument_master_input total=%s nse=%s equity=%s hfcl_present=%s",
        len(rows),
        sum(str(row.get("exchange") or "").strip().upper() == "NSE" for row in rows),
        sum(
            str(row.get("instrument_type") or "").strip().upper() == "EQ"
            for row in rows
        ),
        str(
            any(
                str(row.get("tradingsymbol") or "").strip().upper() == "HFCL"
                for row in rows
            )
        ).lower(),
    )
    instruments = {
        str(row.get("tradingsymbol") or "").strip().upper(): row
        for row in rows
        if str(row.get("exchange") or "").strip().upper() == "NSE"
        and str(row.get("segment") or "NSE").strip().upper() == "NSE"
        and str(row.get("instrument_type") or "").strip().upper() == "EQ"
    }
    if not instruments:
        raise PreflightInputError(
            "The current NSE equity instrument master is unavailable"
        )
    return instruments


def preview_order(
    broker, *, symbol, side, product, quantity, stoploss, target, now=None
):
    symbol = _symbol(symbol)
    if side not in {"BUY", "SHORT"} or product not in {"MIS", "CNC"}:
        raise PreflightInputError("Choose BUY/SHORT and MIS/CNC")
    if side == "SHORT" and product != "MIS":
        raise PreflightInputError(
            "An overnight cash-equity short is not an ordinary CNC entry"
        )
    if type(quantity) is not int or not 1 <= quantity <= 1_000_000:
        raise PreflightInputError("Invalid preview quantity")
    if any(
        type(value) not in {int, float} or not math.isfinite(value) or value <= 0
        for value in (stoploss, target)
    ):
        raise PreflightInputError("Positive finite protective levels are required")
    if broker.health().get("authenticated") is not True:
        raise PreflightInputError("Kite session is not authenticated")
    instrument = _instruments(broker).get(symbol)
    if instrument is None:
        raise PreflightInputError(
            "Symbol is not in Kite's current NSE equity instrument master"
        )
    tick, lot = float(instrument["tick_size"]), int(instrument["lot_size"])
    if not math.isfinite(tick) or tick <= 0 or lot <= 0 or quantity % lot:
        raise PreflightInputError("Invalid instrument tick or lot quantity")
    if any(
        Decimal(str(value)) % Decimal(str(tick)) != 0 for value in (stoploss, target)
    ):
        raise PreflightInputError(
            "Protective levels must match the instrument tick size"
        )
    current = now or datetime.now(TZ)
    current = (
        current.replace(tzinfo=TZ) if current.tzinfo is None else current.astimezone(TZ)
    )
    quote = FreshKitePaperQuotes(broker).prices(["NSE:" + symbol], now=current)[
        "NSE:" + symbol
    ]
    entry = quote["last_price"]
    direction = -1 if side == "SHORT" else 1
    risk, reward = direction * (entry - stoploss), direction * (target - entry)
    if risk <= 0 or reward <= 0:
        ordering = (
            "stop price < fresh quote < target price"
            if side == "BUY"
            else "target price < fresh quote < stop price"
        )
        raise PreflightInputError(
            f"For {side}, require {ordering}. "
            f"Fresh quote: {entry:.2f}; entered stop: {stoploss:.2f}; "
            f"entered target: {target:.2f}. "
            "Enter prices on the correct side of the quote. No order was submitted."
        )
    return {
        "preview_id": "preview-" + uuid4().hex,
        "preview_only": True,
        "symbol": symbol,
        "side": side,
        "product": product,
        "quantity": quantity,
        "reference_price": entry,
        "quote_at": quote["timestamp"],
        "stoploss": stoploss,
        "target": target,
        "gross_notional": entry * quantity,
        "gross_stop_risk": risk * quantity,
        "reward_risk": reward / risk,
        "tick_size": tick,
        "created_at": current.isoformat(),
        "expires_at": (current + timedelta(seconds=30)).isoformat(),
        "broker_orders_allowed": False,
        "orders_submitted": 0,
        "risk_admission": "not_approved_for_real_orders",
        "notes": (
            "Read-only quote-based preview. Funds, live-money policy, execution "
            "lifecycle, fills and protective orders still require verification. "
            "This ID cannot submit an order."
        ),
    }


def scanner_input_checks(broker, *, symbols, mode, period, strategy_id=None, now=None):
    from indicators.indicator_engine import IndicatorEngine
    from scanner.strategy_registry import get_strategy
    from scanner.technical_strategy import strategy_profile
    from services.technical_trading_service import TechnicalTradingService

    if not 1 <= len(symbols) <= 10:
        raise PreflightInputError("Check at most ten symbols")
    symbols = list(dict.fromkeys(_symbol(symbol) for symbol in symbols))
    profile = strategy_profile(mode)
    if period not in profile.allowed_periods:
        raise PreflightInputError("Invalid history period for this mode")
    definition = get_strategy(strategy_id) if strategy_id else None
    if definition and profile.interval not in definition["intervals"]:
        raise PreflightInputError("Strategy interval mismatch")
    current = now or datetime.now(TZ)
    current = (
        current.replace(tzinfo=TZ) if current.tzinfo is None else current.astimezone(TZ)
    )
    try:
        instruments = _instruments(broker)
    except Exception:
        return {
            "checked_at": current.isoformat(),
            "checks": [
                {
                    "symbol": symbol,
                    "status": "blocked",
                    "error_code": "INSTRUMENT_MASTER_UNAVAILABLE",
                }
                for symbol in symbols
            ],
            "broker_orders_allowed": False,
        }
    rows = []
    for symbol in symbols:
        row = {"symbol": symbol, "status": "blocked", "completed_candles": 0}
        if symbol not in instruments:
            row["error_code"] = "NSE_EQUITY_INSTRUMENT_NOT_FOUND"
        else:
            try:
                raw = broker.candles(symbol, period=period, interval=profile.interval)
                candles = (
                    raw
                    if raw.empty
                    else TechnicalTradingService._completed_bars(
                        raw, interval=profile.interval, now=current
                    )
                )
                row["completed_candles"] = len(candles)
                if len(candles) < 60:
                    row["error_code"] = "INSUFFICIENT_COMPLETED_HISTORY"
                else:
                    calculated = IndicatorEngine().calculate(candles)
                    required = (
                        definition["indicators"] if definition else ["ATR", "RSI_14"]
                    )
                    missing = [
                        key
                        for key in required
                        if not math.isfinite(
                            float(calculated.iloc[-1].get(key, float("nan")))
                        )
                    ]
                    row["missing_indicators"] = missing
                    row["latest_bar_at"] = candles.index[-1].isoformat()
                    row["error_code"] = (
                        "INDICATOR_HISTORY_INCOMPLETE" if missing else None
                    )
                    row["status"] = "blocked" if missing else "inputs_available"
            except Exception:
                row["error_code"] = "HISTORY_OR_INDICATOR_CHECK_FAILED"
        rows.append(row)
    return {
        "checked_at": current.isoformat(),
        "instrument_count": len(instruments),
        "reference_reliance_present": "RELIANCE" in instruments,
        "checks": rows,
        "broker_orders_allowed": False,
        "notes": (
            "Current input checks, not reconstruction of the original failure "
            "or trade approval."
        ),
    }
