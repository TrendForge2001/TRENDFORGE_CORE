"""Cross-engine trend consistency and regime-alignment audit.

This module keeps short-horizon price structure distinct from higher-timeframe
trend evidence. A bullish short-term structure is allowed inside a bearish
regime, but it is explicitly labelled counter-trend and receives a conservative
final-signal penalty.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from engines.base_engine import EngineResult


BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"


@dataclass(frozen=True, slots=True)
class TrendAlignment:
    status: str
    market_regime: str
    market_bias: str
    ema_bias: str
    price_action_bias: str
    penalty: float
    conflicts: tuple[str, ...]
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "market_regime": self.market_regime,
            "market_bias": self.market_bias,
            "ema_bias": self.ema_bias,
            "price_action_bias": self.price_action_bias,
            "penalty": self.penalty,
            "conflicts": list(self.conflicts),
            "message": self.message,
        }


def _result(results: Mapping[str, EngineResult] | None, name: str) -> EngineResult | None:
    value = (results or {}).get(name)
    return value if isinstance(value, EngineResult) else None


def _metric(result: EngineResult | None, key: str, default: Any = None) -> Any:
    metrics = getattr(result, "metrics", None)
    return metrics.get(key, default) if isinstance(metrics, dict) else default


def _number(result: EngineResult | None, key: str) -> float | None:
    try:
        value = float(_metric(result, key))
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _direction(value: Any) -> str:
    value = str(value or "").strip().upper()
    return value if value in {BULLISH, BEARISH} else NEUTRAL


def _market_evidence(result: EngineResult | None) -> tuple[str, str]:
    regime = str(_metric(result, "regime", "UNKNOWN") or "UNKNOWN").strip().upper()
    if regime == BULLISH:
        return regime, BULLISH
    if regime in {BEARISH, "RISK_OFF"}:
        return regime, BEARISH
    return regime, NEUTRAL


def _ema_bias(result: EngineResult | None) -> str:
    close = _number(result, "close")
    ema20 = _number(result, "EMA_20")
    ema50 = _number(result, "EMA_50")
    ema200 = _number(result, "EMA_200")
    if None in {close, ema20, ema50, ema200}:
        return NEUTRAL
    if close > ema20 > ema50 > ema200:
        return BULLISH
    if close < ema20 < ema50 < ema200:
        return BEARISH
    return NEUTRAL


def _price_action_bias(result: EngineResult | None) -> str:
    direction = _direction(_metric(result, "direction"))
    if direction != NEUTRAL:
        return direction
    uptrend = bool(_metric(result, "uptrend", False))
    downtrend = bool(_metric(result, "downtrend", False))
    if uptrend and not downtrend:
        return BULLISH
    if downtrend and not uptrend:
        return BEARISH
    return NEUTRAL


def evaluate_trend_alignment(
    results: Mapping[str, EngineResult] | None,
) -> TrendAlignment:
    """Reconcile short-term structure with regime and EMA-stack evidence.

    Penalty design is intentionally bounded:
    - 8 points when price action conflicts with the market regime.
    - 4 points when price action conflicts with a fully ordered EMA stack.
    - 12 points maximum.

    Neutral or unavailable evidence never creates a penalty.
    """

    market = _result(results, "Market Regime Engine")
    technical = _result(results, "Technical Engine")
    price_action = _result(results, "Price Action Engine")

    market_regime, market_bias = _market_evidence(market)
    ema_bias = _ema_bias(technical)
    price_bias = _price_action_bias(price_action)

    conflicts: list[str] = []
    penalty = 0.0

    if (
        price_bias != NEUTRAL
        and market_bias != NEUTRAL
        and price_bias != market_bias
    ):
        conflicts.append("price_action_vs_market_regime")
        penalty += 8.0

    if (
        price_bias != NEUTRAL
        and ema_bias != NEUTRAL
        and price_bias != ema_bias
    ):
        conflicts.append("price_action_vs_ema_stack")
        penalty += 4.0

    penalty = min(12.0, penalty)

    if price_bias == NEUTRAL:
        status = "INSUFFICIENT"
        message = "Short-term price-action direction is neutral or unavailable."
    elif conflicts:
        status = "COUNTER_TREND"
        evidence: list[str] = []
        if "price_action_vs_market_regime" in conflicts:
            evidence.append(f"{market_regime.lower()} market regime")
        if "price_action_vs_ema_stack" in conflicts:
            evidence.append(f"{ema_bias.lower()} EMA stack")
        message = (
            f"Short-term {price_bias.lower()} price structure is counter-trend to "
            + " and ".join(evidence)
            + "."
        )
    elif price_bias in {market_bias, ema_bias}:
        status = "ALIGNED"
        message = (
            f"Short-term {price_bias.lower()} price structure is aligned with "
            "higher-timeframe trend evidence."
        )
    else:
        status = "MIXED"
        message = (
            f"Short-term {price_bias.lower()} price structure has mixed or neutral "
            "higher-timeframe confirmation."
        )

    return TrendAlignment(
        status=status,
        market_regime=market_regime,
        market_bias=market_bias,
        ema_bias=ema_bias,
        price_action_bias=price_bias,
        penalty=penalty,
        conflicts=tuple(conflicts),
        message=message,
    )


__all__ = ["TrendAlignment", "evaluate_trend_alignment"]
