"""Three research scanner choices per timeframe, sharing registered evaluators."""

from __future__ import annotations

import math

from scanner.multi_strategy_engine import MultiStrategyEngine
from scanner.strategy_registry import get_strategy
from scanner.technical_strategy import latest_signal, strategy_profile


def strategy_choices(mode: str) -> dict[str, str | None]:
    mode = strategy_profile(mode).mode
    return {
        "Technical Momentum": None,
        "EMA 20/50 + RSI + Volume": f"tf_{mode}_ema20_50_rsi_volume",
        "VWMA 9/26 + RSI + Volume": f"tf_{mode}_vwma9_26_rsi_volume",
    }


def validate_workspace_strategy(mode: str, strategy_id: str | None) -> dict | None:
    if strategy_id is None:
        strategy_profile(mode)
        return None
    if strategy_id not in strategy_choices(mode).values():
        raise ValueError("Choose a supported scanner strategy for this timeframe")
    return get_strategy(strategy_id)


def workspace_signal(frame, profile, strategy_id: str | None) -> dict:
    if strategy_id is None:
        return latest_signal(frame, profile)
    result = MultiStrategyEngine().evaluate(
        frame,
        mode=profile.mode,
        interval=profile.interval,
        strategy_ids=[strategy_id],
    )["evaluations"][0]
    if result.get("status") != "evaluated":
        raise ValueError("The scanner strategy could not be evaluated")
    indicators = {}
    for key in get_strategy(strategy_id)["indicators"]:
        try:
            value = float(frame.iloc[-1].get(key))
            indicators[key] = value if math.isfinite(value) else None
        except (ValueError, TypeError):
            indicators[key] = None
    return {
        "signal": result["signal"],
        "score": result["score"],
        "confidence": result["score"],
        "trigger": result["signal"],
        "risk": result["risk"],
        "evidence": result["checks"],
        "indicators": {
            key: indicators.get(key) for key in get_strategy(strategy_id)["indicators"]
        },
    }
