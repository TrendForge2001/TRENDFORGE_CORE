"""Read-only daily confirmation, separate from the institutional activity rule."""

from datetime import UTC, datetime

import pandas as pd

from scanner.portfolio_policy import number
from scanner.vwma_yearly import LEVELS, prepare_daily
from services.big_shark_activity import activity_view
from services.technical_trading_service import TechnicalTradingService

RULE = "big-shark-daily-confirmation-v1"


def evaluate_daily(frame, *, now):
    daily = prepare_daily(frame, now=now)
    current, previous = daily.iloc[-1], daily.iloc[-2]
    stamp = pd.Timestamp(daily.index[-1])
    close_at = stamp.normalize() + pd.Timedelta(hours=15, minutes=30)
    values = {
        key: number(current.get(key))
        for key in (
            "close",
            "volume",
            "VWMA_20",
            "VWMA_50",
            "RSI_WILDER_14",
            "VOL_SMA_20",
            *("FIB_YEAR_" + name for name in LEVELS),
        )
    }
    common = {
        "rule": RULE,
        "bar_closed_at": close_at.isoformat(),
        "checked_at": now.astimezone(UTC).isoformat(),
        "indicators": values,
    }
    if any(v is None for v in values.values()):
        return {
            **common,
            "price_signal": "NO_DATA",
            "reason": "Insufficient indicators or previous-year coverage",
        }
    if TechnicalTradingService._execution_block_reason(daily, mode="swing", now=now):
        return {
            **common,
            "price_signal": "STALE_DATA",
            "reason": "Latest completed daily session is missing",
        }
    c, pc = values["close"], number(previous.get("close"))
    w20, w50 = values["VWMA_20"], values["VWMA_50"]
    pw20 = number(previous.get("VWMA_20"))
    rsi = values["RSI_WILDER_14"]
    same_year = current.name.year == previous.name.year
    resistance = [
        name
        for name in ("R1", "R2", "R3")
        if same_year and pc is not None and pc <= values["FIB_YEAR_" + name] < c
    ]
    support = [
        name
        for name in ("P", "S1", "S2", "S3")
        if same_year and pc is not None and pc >= values["FIB_YEAR_" + name] > c
    ]
    buy = {
        "close_above_vwma20_above_vwma50": c > w20 > w50,
        "rsi_55_to_75": 55 <= rsi <= 75,
        "volume_at_least_1_5_sma20": values["VOL_SMA_20"] > 0
        and values["volume"] >= 1.5 * values["VOL_SMA_20"],
        "fresh_yearly_resistance_breakout": bool(resistance),
    }
    sell = {
        "rsi_below_50": rsi < 50,
        "fresh_vwma20_or_yearly_support_breakdown": bool(support)
        or (None not in (pc, pw20) and pc >= pw20 and c < w20),
    }
    return {
        **common,
        "price_signal": "BUY"
        if all(buy.values())
        else "SELL_EXIT"
        if all(sell.values())
        else "WAIT",
        "buy_checks": buy,
        "sell_checks": sell,
        "crossed_resistance": resistance,
        "crossed_support": support,
    }


def refresh_confirmations(
    snapshot, market_data, symbols, *, now=None, horizon="short_term"
):
    now = now or datetime.now(UTC)
    from services.institutional_stock_rating import HORIZONS, technical_evidence

    if horizon not in HORIZONS:
        raise ValueError("Choose Short Term or Long Term for stock ratings")
    result = activity_view(snapshot, now=now)
    rows = {r["symbol"]: r for r in result["signals"] if r.get("symbol")}
    if not symbols or len(symbols) > 5 or len(set(symbols)) != len(symbols):
        raise ValueError("Choose between one and five distinct mapped stocks.")
    if any(symbol not in rows for symbol in symbols):
        raise ValueError(
            "Technical checks require symbols from this private activity snapshot."
        )
    for symbol in symbols:
        row = rows[symbol]
        try:
            raw = market_data.candles(symbol, period="5y", interval="1d")
            evidence = evaluate_daily(raw, now=now)
            rating_technical = technical_evidence(raw, horizon=horizon, now=now)
        except Exception:
            # Provider error text may contain credentials and must stay private.
            evidence = {
                "rule": RULE,
                "price_signal": "NO_DATA",
                "reason": "Completed daily candles are unavailable or invalid",
                "checked_at": now.astimezone(UTC).isoformat(),
            }
            rating_technical = {
                "status": "NO_DATA",
                "reason": "Completed daily candles are unavailable",
            }
        price_signal = evidence["price_signal"]
        activity = row["activity_signal"]
        confirmation = (
            price_signal if price_signal in {"NO_DATA", "STALE_DATA"} else "WAIT"
        )
        if activity == "NO_DATA":
            confirmation = "NO_ACTIVITY_DATA"
        elif price_signal == "BUY" and activity == "BUY":
            confirmation = "BUY_CONFIRMED"
        elif price_signal == "SELL_EXIT" and activity == "SELL":
            confirmation = "SELL_EXIT_CONFIRMED"
        row["technical_confirmation"] = confirmation
        row["technical_evidence"] = evidence
        row["technical_checked_at"] = now.astimezone(UTC).isoformat()
        row.setdefault("rating_technicals", {})[horizon] = rating_technical
    result["execution_enabled"] = False
    return result
