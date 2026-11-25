"""Explainable, read-only stock ratings from disclosed flows and closed candles."""

import copy
import json
from datetime import UTC, date, datetime

import pandas as pd

from scanner.portfolio_policy import number
from scanner.vwma_yearly import prepare_daily
from services.technical_trading_service import TechnicalTradingService
from services.trading_calendar import latest_completed_session

RULE = "institutional-technical-rating-v1"
HORIZONS = ("short_term", "long_term")
MAX_ACTIVITY_AGE_DAYS = 7
POLICY = {
    "rule": RULE,
    "institutional_max_points": 40,
    "technical_max_points": 60,
    "technical_components": {
        "trend": 20,
        "momentum": 15,
        "volume": 15,
        "yearly_pivot": 10,
    },
    "activity_age_limit_calendar_days": MAX_ACTIVITY_AGE_DAYS,
    "strong_buy_minimum": 80,
    "buy_minimum": 65,
    "meaning": "Heuristic confluence score, not a probability or backtested return",
    "execution_enabled": False,
}


def technical_evidence(frame, *, horizon, now):
    if horizon not in HORIZONS:
        raise ValueError("Ratings support Short Term and Long Term")
    common = {
        "rule": RULE,
        "horizon": horizon,
        "checked_at": now.astimezone(UTC).isoformat(),
    }
    try:
        daily = prepare_daily(frame, now=now)
        required = 200 if horizon == "long_term" else 50
        if len(daily) < required:
            return {
                **common,
                "status": "NO_DATA",
                "reason": "Insufficient completed daily history",
            }
        if TechnicalTradingService._execution_block_reason(
            daily, mode="swing", now=now
        ):
            return {
                **common,
                "status": "STALE_DATA",
                "reason": "Latest completed daily session is missing",
            }
        for length in (20, 50, 100, 200):
            daily[f"EMA_{length}"] = daily.close.ewm(
                span=length, adjust=False, min_periods=length
            ).mean()
        row = daily.iloc[-1]
        keys = [
            "close",
            "volume",
            "EMA_20",
            "EMA_50",
            "VWMA_20",
            "VWMA_50",
            "RSI_WILDER_14",
            "VOL_SMA_20",
            "FIB_YEAR_P",
            "FIB_YEAR_S1",
        ]
        if horizon == "long_term":
            keys += ["EMA_100", "EMA_200"]
        values = {key: number(row.get(key)) for key in keys}
        if any(value is None for value in values.values()) or values["VOL_SMA_20"] <= 0:
            return {
                **common,
                "status": "NO_DATA",
                "reason": "Indicators or previous-year pivot history are incomplete",
            }
        closed = pd.Timestamp(daily.index[-1]).normalize() + pd.Timedelta(
            hours=15, minutes=30
        )
        return {
            **common,
            "status": "READY",
            "bar_closed_at": closed.isoformat(),
            "indicators": values,
        }
    except Exception:
        return {
            **common,
            "status": "NO_DATA",
            "reason": "Completed daily technical evidence is unavailable",
        }


def _blank(horizon, now, reason, *, coverage=None):
    return {
        "rule": RULE,
        "horizon": horizon,
        "rating": "INSUFFICIENT_DATA",
        "score": None,
        "institutional_score": None,
        "technical_score": None,
        "reason": reason,
        "data_coverage": coverage,
        "as_of": now.astimezone(UTC).isoformat(),
        "execution_enabled": False,
    }


def assess_technical(technical, *, horizon="short_term", now=None):
    """Expose the existing 60-point component without inventing institutional data."""
    from services.big_shark_activity import TZ

    now = now or datetime.now(UTC)
    if now.tzinfo is None or horizon not in HORIZONS:
        raise ValueError("Explicit rating horizon and timezone required")
    current = now.astimezone(TZ)

    def blank(reason):
        return {
            "status": "UNAVAILABLE",
            "score": None,
            "max_score": 60,
            "state": "UNAVAILABLE",
            "reason": reason,
            "points": {},
        }

    if (
        technical.get("rule") != RULE
        or technical.get("horizon") != horizon
        or technical.get("status") != "READY"
    ):
        return blank(
            technical.get("reason") or "Daily technical evidence has not been checked"
        )
    try:
        closed = datetime.fromisoformat(technical["bar_closed_at"])
        checked = datetime.fromisoformat(technical["checked_at"])
        if (
            closed.tzinfo is None
            or checked.tzinfo is None
            or max(closed, checked) > now
            or (closed.astimezone(TZ).date() != latest_completed_session(current))
        ):
            return blank("Daily technical evidence is stale or not yet closed")
    except (KeyError, TypeError, ValueError):
        return blank("Daily technical timestamps are unavailable")
    indicators = technical.get("indicators") or {}
    keys = (
        "close",
        "EMA_20",
        "EMA_50",
        "VWMA_20",
        "VWMA_50",
        "RSI_WILDER_14",
        "volume",
        "VOL_SMA_20",
        "FIB_YEAR_P",
        "FIB_YEAR_S1",
    )
    values = {key: number(indicators.get(key)) for key in keys}
    if horizon == "long_term":
        values.update(
            {key: number(indicators.get(key)) for key in ("EMA_100", "EMA_200")}
        )
    if any(v is None for v in values.values()) or values["VOL_SMA_20"] <= 0:
        return blank("Daily technical indicator values are incomplete")
    c, rsi = values["close"], values["RSI_WILDER_14"]
    if not 0 <= rsi <= 100 or c <= 0 or values["volume"] < 0:
        return blank("Daily technical indicator values are invalid")
    if any(
        value <= 0
        for key, value in values.items()
        if key not in {"volume", "RSI_WILDER_14"}
    ):
        return blank("Moving averages and yearly pivot prices must be positive")
    ema_up = (
        c > values["EMA_20"] > values["EMA_50"]
        if horizon == "short_term"
        else (c > values["EMA_50"] > values["EMA_100"] > values["EMA_200"])
    )
    ema_down = (
        c < values["EMA_20"] < values["EMA_50"]
        if horizon == "short_term"
        else (c < values["EMA_50"] < values["EMA_100"] < values["EMA_200"])
    )
    up = ema_up and c > values["VWMA_20"] > values["VWMA_50"]
    down = ema_down and c < values["VWMA_20"] < values["VWMA_50"]
    high_volume = values["volume"] > values["VOL_SMA_20"]
    state = (
        "BULLISH"
        if up and 50 < rsi <= 70 and high_volume
        else ("BEARISH" if down and rsi < 50 and high_volume else "NEUTRAL")
    )
    points = {
        "trend": 20 if up else 0 if down else 10,
        "momentum": 15 if 50 < rsi <= 70 else 0 if rsi < 50 else 7.5,
        "volume": 15 if high_volume else 0,
        "yearly_pivot": 10
        if c > values["FIB_YEAR_P"]
        else 5
        if c > values["FIB_YEAR_S1"]
        else 0,
    }
    return {
        "status": "READY",
        "score": sum(points.values()),
        "max_score": 60,
        "state": state,
        "points": points,
        "bar_closed_at": technical["bar_closed_at"],
        "indicators": values,
        "reason": (
            "Completed daily technical component; "
            "institutional activity is assessed separately"
        ),
    }


def rate(row, technical, *, horizon="short_term", now=None):
    now = now or datetime.now(UTC)
    if now.tzinfo is None or horizon not in HORIZONS:
        raise ValueError("Explicit rating horizon and timezone required")
    from services.big_shark_activity import TZ

    current = now.astimezone(TZ)
    coverage = row.get("data_coverage", "NO_TRADE_DATA")

    def blank(reason):
        return _blank(horizon, now, reason, coverage=coverage)

    buy, sell = number(row.get("avg_buy")), number(row.get("avg_sell"))
    if not row.get("observations") or None in (buy, sell) or min(buy, sell) < 0:
        return blank(
            "Actual institutional bought/sold quantities or values are missing"
        )
    if row.get("missing_or_invalid") or coverage in {"NO_TRADE_DATA", "PARTIAL_INPUT"}:
        return blank("Institutional trade inputs are incomplete")
    if row.get("metric") not in {"quantity", "value"}:
        return blank("Use one actual trade metric")
    try:
        start, end = (
            date.fromisoformat(str(row.get(key)))
            for key in ("period_start", "period_end")
        )
        if start > end or end > current.date():
            return blank("Institutional reporting window is invalid or future dated")
        if (current.date() - end).days > MAX_ACTIVITY_AGE_DAYS:
            return blank(
                "Institutional reporting window is older than seven calendar days"
            )
        for field in ("first_seen_at", "disclosure_time"):
            if row.get(field):
                stamp = datetime.fromisoformat(row[field])
                if stamp.tzinfo is None or stamp > now:
                    return blank(
                        "Institutional evidence was not available at this rating time"
                    )
    except (TypeError, ValueError):
        return blank("Institutional reporting dates are missing or invalid")
    assessed = assess_technical(technical, horizon=horizon, now=now)
    if assessed["status"] != "READY":
        return blank(assessed["reason"])
    state, points = assessed["state"], assessed["points"]
    institutional = 40 * buy / (buy + sell) if buy + sell > 0 else 20
    technical_score = sum(points.values())
    score = round(institutional + technical_score, 2)
    activity = "BUY" if buy > sell else "SELL" if sell > buy else "HOLD"
    if (activity, state) in {("BUY", "BEARISH"), ("SELL", "BULLISH")}:
        rating, reason = (
            "CONFLICT",
            "Institutional activity and technical confirmation disagree",
        )
    elif activity == "SELL" and state == "BEARISH":
        rating, reason = (
            "EXIT",
            "Disclosed selling and completed bearish technicals align; long exits only",
        )
    elif activity == "BUY" and state == "BULLISH" and score >= 65:
        rating = "STRONG_BUY" if score >= 80 else "BUY"
        reason = (
            "Disclosed buying and completed EMA/VWMA, RSI and volume confirmation align"
        )
    else:
        rating = "HOLD" if activity == "HOLD" and state == "NEUTRAL" else "WATCH"
        reason = "Wait for institutional and technical alignment"
    return {
        "rule": RULE,
        "horizon": horizon,
        "rating": rating,
        "score": score,
        "institutional_score": round(institutional, 2),
        "technical_score": technical_score,
        "activity_signal": activity,
        "technical_state": state,
        "technical_points": points,
        "reason": reason,
        "data_coverage": coverage,
        "activity_window_end": end.isoformat(),
        "bar_closed_at": technical["bar_closed_at"],
        "disclosure_time": row.get("disclosure_time"),
        "as_of": now.astimezone(UTC).isoformat(),
        "execution_enabled": False,
        "limitations": [
            "Disclosed/owner-supplied trades only; unreported trading remains unknown",
            "Publication time is unknown unless explicitly supplied; "
            "no historical timing claim",
            "Heuristic score, not a probability or approval to automate trades",
        ],
    }


def view(snapshot, *, horizon="short_term", now=None):
    from services.big_shark_activity import activity_view

    now = now or datetime.now(UTC)
    result = activity_view(snapshot, now=now)
    result["rating_policy"] = copy.deepcopy(POLICY)
    for row in result.get("signals", []):
        evidence = (row.get("rating_technicals") or {}).get(horizon, {})
        rating = rate(row, evidence, horizon=horizon, now=now)
        row.update(
            {
                "stock_rating": rating["rating"],
                "rating_score": rating["score"],
                "institutional_score": rating["institutional_score"],
                "technical_score": rating["technical_score"],
                "rating_horizon": horizon,
                "rating_reason": rating["reason"],
                "rating_evidence": rating,
            }
        )
    return result


def scanner_rating(row, frame, *, horizon, now):
    if not row:
        return _blank(
            horizon,
            now,
            "No matched actual institutional trade data for this stock",
            coverage="NO_TRADE_DATA",
        )
    return rate(
        row,
        technical_evidence(frame, horizon=horizon, now=now),
        horizon=horizon,
        now=now,
    )


def load_snapshot(technical):
    """Read the current owner's private snapshot; do not import or refresh sources."""
    from services.big_shark_activity import activity_view

    try:
        saved = technical.repository.db.fetchone(
            "SELECT payload_json FROM big_shark_portfolios ORDER BY rowid DESC LIMIT 1"
        )
        snapshot = json.loads(saved["payload_json"]) if saved else None
        return (
            {
                row["symbol"]: row
                for row in activity_view(snapshot).get("signals", [])
                if row.get("symbol")
            }
            if snapshot
            else {}
        )
    except Exception:
        return {}
