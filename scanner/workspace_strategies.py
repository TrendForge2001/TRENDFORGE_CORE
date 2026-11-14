"""Source-derived active scanner choices; retired rules cannot be selected."""

from __future__ import annotations

import math

from scanner.multi_strategy_engine import MultiStrategyEngine
from scanner.portfolio_policy import number
from scanner.strategy_registry import (
    get_strategy,
    list_scanner_choices,
    list_strategies,
)
from scanner.technical_strategy import latest_signal, strategy_profile


def strategy_choices(mode: str) -> dict[str, str | None]:
    if mode not in {"intraday", "swing", "positional"}:
        raise ValueError("Unknown scanner mode")
    return {row["name"]: row["strategy_id"] for row in list_scanner_choices(mode=mode)}


def default_legacy_strategy(mode: str) -> str:
    """Preserve existing backend defaults independently of new UI choices."""
    strategy_profile(mode)
    return list_strategies(mode=mode)[0]["strategy_id"]


def validate_workspace_strategy(mode: str, strategy_id: str | None) -> dict | None:
    if strategy_id is None:
        strategy_profile(mode)
        return None
    # Explicit legacy IDs remain usable by authenticated historical clients and
    # existing exit lineage. They are never offered as new UI scanner choices.
    try:
        definition = get_strategy(strategy_id)
    except KeyError:
        raise ValueError(
            "Choose a supported scanner strategy for this timeframe"
        ) from None
    if mode not in definition["modes"]:
        raise ValueError("Choose a supported scanner strategy for this timeframe")
    return definition


def workspace_signal(
    frame,
    profile,
    strategy_id: str | None,
    *,
    liquidity_confirmation=False,
    tick_size=0.05,
) -> dict:
    if strategy_id is None:
        return latest_signal(frame, profile)
    result = MultiStrategyEngine().evaluate(
        frame,
        mode=profile.mode,
        interval=profile.interval,
        strategy_ids=[strategy_id],
        liquidity_confirmation=liquidity_confirmation,
        tick_size=tick_size,
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
        "entry_plan": result.get("entry_plan"),
        "entry_state": result.get("entry_state"),
        "evidence": result["checks"],
        "indicators": {
            **{
                key: indicators.get(key)
                for key in get_strategy(strategy_id)["indicators"]
            },
            "volume": number(frame.iloc[-1].get("volume")),
            "close": number(frame.iloc[-1].get("close")),
        },
    }
