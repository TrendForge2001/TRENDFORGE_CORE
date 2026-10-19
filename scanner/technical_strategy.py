"""Technical-only strategy profiles for TrendForge research and paper trading.

R71.2 deliberately excludes fundamentals and enrichment.  It converts the
canonical indicator frame into transparent long-only intraday or swing
signals that can be consumed by both the historical backtest engine and the
paper-trading safety boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import pandas as pd


@dataclass(frozen=True, slots=True)
class TechnicalStrategyProfile:
    mode: str
    interval: str
    default_period: str
    allowed_periods: tuple[str, ...]
    entry_score: float
    exit_score: float
    rsi_min: float
    rsi_max: float
    adx_min: float
    rvol_min: float
    stop_atr: float
    reward_risk: float


PROFILES: dict[str, TechnicalStrategyProfile] = {
    "intraday": TechnicalStrategyProfile(
        mode="intraday",
        interval="15m",
        default_period="60d",
        allowed_periods=("30d", "45d", "60d"),
        entry_score=75.0,
        exit_score=45.0,
        rsi_min=55.0,
        rsi_max=75.0,
        adx_min=20.0,
        rvol_min=1.20,
        stop_atr=1.50,
        reward_risk=2.0,
    ),
    "swing": TechnicalStrategyProfile(
        mode="swing",
        interval="1d",
        default_period="2y",
        allowed_periods=("1y", "2y", "5y"),
        entry_score=75.0,
        exit_score=45.0,
        rsi_min=55.0,
        rsi_max=78.0,
        adx_min=18.0,
        rvol_min=1.00,
        stop_atr=2.00,
        reward_risk=2.0,
    ),
}


def strategy_profile(mode: str) -> TechnicalStrategyProfile:
    key = str(mode or "").strip().lower()
    try:
        return PROFILES[key]
    except KeyError as exc:
        raise ValueError("mode must be intraday or swing") from exc


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    number = _finite(value)
    if number is not None:
        return bool(number)
    return str(value or "").strip().lower() in {"true", "yes", "bullish", "up"}


def _cross_above(previous: pd.Series, current: pd.Series, fast: str, slow: str) -> bool:
    previous_fast = _finite(previous.get(fast))
    previous_slow = _finite(previous.get(slow))
    current_fast = _finite(current.get(fast))
    current_slow = _finite(current.get(slow))
    if None in (previous_fast, previous_slow, current_fast, current_slow):
        return False
    return bool(previous_fast <= previous_slow and current_fast > current_slow)


def _cross_below(previous: pd.Series, current: pd.Series, fast: str, slow: str) -> bool:
    previous_fast = _finite(previous.get(fast))
    previous_slow = _finite(previous.get(slow))
    current_fast = _finite(current.get(fast))
    current_slow = _finite(current.get(slow))
    if None in (previous_fast, previous_slow, current_fast, current_slow):
        return False
    return bool(previous_fast >= previous_slow and current_fast < current_slow)


def _above(row: pd.Series, left: str, right: str) -> bool:
    a = _finite(row.get(left))
    b = _finite(row.get(right))
    return bool(a is not None and b is not None and a > b)


def _range(row: pd.Series, key: str, low: float, high: float) -> bool:
    value = _finite(row.get(key))
    return bool(value is not None and low <= value <= high)


def _gte(row: pd.Series, key: str, threshold: float) -> bool:
    value = _finite(row.get(key))
    return bool(value is not None and value >= threshold)


def score_row(
    row: pd.Series,
    profile: TechnicalStrategyProfile,
) -> tuple[float, dict[str, bool]]:
    """Return a 0-100 technical score with fully exposed evidence."""

    if profile.mode == "intraday":
        checks = {
            "ema9_above_ema20": _above(row, "EMA_9", "EMA_20"),
            "ema20_above_ema50": _above(row, "EMA_20", "EMA_50"),
            "vwma9_above_vwma26": _above(row, "VWMA_9", "VWMA_26"),
            "close_above_vwap": _above(row, "close", "VWAP"),
            "rsi_in_momentum_band": _range(
                row,
                "RSI",
                profile.rsi_min,
                profile.rsi_max,
            ),
            "macd_bullish": (
                _above(row, "MACD", "MACD_SIGNAL")
                and (_finite(row.get("MACD_HIST")) or 0.0) > 0.0
            ),
            "adx_directional_strength": (
                _gte(row, "ADX", profile.adx_min)
                and _above(row, "+DI", "-DI")
            ),
            "relative_volume": _gte(row, "RVOL", profile.rvol_min),
        }
        weights = {
            "ema9_above_ema20": 15.0,
            "ema20_above_ema50": 10.0,
            "vwma9_above_vwma26": 10.0,
            "close_above_vwap": 15.0,
            "rsi_in_momentum_band": 15.0,
            "macd_bullish": 15.0,
            "adx_directional_strength": 10.0,
            "relative_volume": 10.0,
        }
    else:
        checks = {
            "ema20_above_ema50": _above(row, "EMA_20", "EMA_50"),
            "ema50_above_ema100": _above(row, "EMA_50", "EMA_100"),
            "close_above_ema20": _above(row, "close", "EMA_20"),
            "vwma9_above_vwma26": _above(row, "VWMA_9", "VWMA_26"),
            "rsi_in_momentum_band": _range(
                row,
                "RSI",
                profile.rsi_min,
                profile.rsi_max,
            ),
            "macd_bullish": (
                _above(row, "MACD", "MACD_SIGNAL")
                and (_finite(row.get("MACD_HIST")) or 0.0) > 0.0
            ),
            "adx_directional_strength": (
                _gte(row, "ADX", profile.adx_min)
                and _above(row, "+DI", "-DI")
            ),
            "relative_volume": _gte(row, "RVOL", profile.rvol_min),
        }
        weights = {
            "ema20_above_ema50": 20.0,
            "ema50_above_ema100": 10.0,
            "close_above_ema20": 10.0,
            "vwma9_above_vwma26": 10.0,
            "rsi_in_momentum_band": 15.0,
            "macd_bullish": 15.0,
            "adx_directional_strength": 10.0,
            "relative_volume": 10.0,
        }

    score = sum(weights[name] for name, passed in checks.items() if passed)
    return round(score, 2), checks


def _fresh_entry_trigger(
    previous: pd.Series,
    current: pd.Series,
    profile: TechnicalStrategyProfile,
) -> tuple[bool, str | None]:
    if profile.mode == "intraday":
        if _cross_above(previous, current, "EMA_9", "EMA_20"):
            return True, "EMA9_CROSS_ABOVE_EMA20"
        if _boolean(current.get("BREAKOUT")) and not _boolean(previous.get("BREAKOUT")):
            return True, "FRESH_BREAKOUT"
        return False, None

    if _cross_above(previous, current, "EMA_20", "EMA_50"):
        return True, "EMA20_CROSS_ABOVE_EMA50"
    if _boolean(current.get("BREAKOUT")) and not _boolean(previous.get("BREAKOUT")):
        return True, "FRESH_BREAKOUT"

    previous_close = _finite(previous.get("close"))
    previous_ema20 = _finite(previous.get("EMA_20"))
    close = _finite(current.get("close"))
    ema20 = _finite(current.get("EMA_20"))
    if (
        previous_close is not None
        and previous_ema20 is not None
        and close is not None
        and ema20 is not None
        and previous_close <= previous_ema20
        and close > ema20
    ):
        return True, "EMA20_RECLAIM"
    return False, None


def entry_decision(
    previous: pd.Series,
    current: pd.Series,
    profile: TechnicalStrategyProfile,
) -> dict[str, Any] | None:
    score, evidence = score_row(current, profile)
    fresh_trigger, trigger = _fresh_entry_trigger(previous, current, profile)
    if score < profile.entry_score or not fresh_trigger:
        return None

    close = _finite(current.get("close"))
    atr = _finite(current.get("ATR"))
    if close is None or close <= 0 or atr is None or atr <= 0:
        return None

    stoploss = max(0.01, close - profile.stop_atr * atr)
    target2 = close + profile.reward_risk * (close - stoploss)
    return {
        "signal": "BUY",
        "score": score,
        "confidence": score,
        "trigger": trigger,
        "entry": round(close, 6),
        "stoploss": round(stoploss, 6),
        "target2": round(target2, 6),
        "reward_risk": profile.reward_risk,
        "evidence": evidence,
    }


def exit_decision(
    previous: pd.Series,
    current: pd.Series,
    profile: TechnicalStrategyProfile,
) -> dict[str, Any] | None:
    score, evidence = score_row(current, profile)
    rsi = _finite(current.get("RSI"))
    macd_bearish = not _above(current, "MACD", "MACD_SIGNAL")

    if profile.mode == "intraday":
        reversal = _cross_below(previous, current, "EMA_9", "EMA_20")
        below_reference = not _above(current, "close", "VWAP")
        reason = (
            "EMA9_CROSS_BELOW_EMA20"
            if reversal
            else "CLOSE_BELOW_VWAP"
            if below_reference
            else "RSI_MOMENTUM_LOSS"
            if rsi is not None and rsi < 50.0
            else "MACD_BEARISH"
            if macd_bearish
            else "TECHNICAL_SCORE_EXIT"
        )
        should_exit = bool(
            reversal
            or below_reference
            or (rsi is not None and rsi < 50.0)
            or macd_bearish
            or score <= profile.exit_score
        )
    else:
        reversal = _cross_below(previous, current, "EMA_20", "EMA_50")
        below_reference = not _above(current, "close", "EMA_20")
        reason = (
            "EMA20_CROSS_BELOW_EMA50"
            if reversal
            else "CLOSE_BELOW_EMA20"
            if below_reference
            else "RSI_MOMENTUM_LOSS"
            if rsi is not None and rsi < 50.0
            else "MACD_BEARISH"
            if macd_bearish
            else "TECHNICAL_SCORE_EXIT"
        )
        should_exit = bool(
            reversal
            or below_reference
            or (rsi is not None and rsi < 50.0)
            or macd_bearish
            or score <= profile.exit_score
        )

    if not should_exit:
        return None
    return {
        "reason": reason,
        "score": score,
        "evidence": evidence,
    }


def latest_signal(
    frame: pd.DataFrame,
    profile: TechnicalStrategyProfile,
) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame) or len(frame) < 2:
        raise ValueError("Technical signal requires at least two completed bars")

    previous = frame.iloc[-2]
    current = frame.iloc[-1]
    score, evidence = score_row(current, profile)
    entry = entry_decision(previous, current, profile)
    exit_signal = exit_decision(previous, current, profile)

    close = _finite(current.get("close"))
    atr = _finite(current.get("ATR"))
    risk: dict[str, float | None] = {
        "entry": close,
        "stoploss": None,
        "target2": None,
        "reward_risk": profile.reward_risk,
    }
    if close is not None and close > 0 and atr is not None and atr > 0:
        stoploss = max(0.01, close - profile.stop_atr * atr)
        risk["stoploss"] = round(stoploss, 6)
        risk["target2"] = round(
            close + profile.reward_risk * (close - stoploss),
            6,
        )

    signal = "BUY" if entry is not None else "EXIT" if exit_signal else "HOLD"
    trigger = (
        entry.get("trigger")
        if entry is not None
        else exit_signal.get("reason")
        if exit_signal is not None
        else None
    )
    return {
        "signal": signal,
        "score": score,
        "confidence": score,
        "trigger": trigger,
        "risk": risk,
        "evidence": evidence,
        "indicators": {
            key: _finite(current.get(key))
            for key in (
                "close",
                "EMA_9",
                "EMA_20",
                "EMA_50",
                "EMA_100",
                "EMA_200",
                "VWMA_9",
                "VWMA_26",
                "VWAP",
                "RSI",
                "MACD",
                "MACD_SIGNAL",
                "MACD_HIST",
                "ADX",
                "+DI",
                "-DI",
                "ATR",
                "RVOL",
            )
        },
    }


__all__ = [
    "PROFILES",
    "TechnicalStrategyProfile",
    "entry_decision",
    "exit_decision",
    "latest_signal",
    "score_row",
    "strategy_profile",
]
