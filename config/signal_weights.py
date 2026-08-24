"""Canonical weights for final TrendForge signal aggregation."""

SIGNAL_WEIGHTS = {
    "market": 0.10,
    "sector": 0.10,
    "fundamental": 0.20,
    "corporate": 0.10,
    "big_shark": 0.15,
    "technical": 0.20,
    "price_action": 0.10,
    "risk": 0.05,
}

WEIGHT_SUM = sum(SIGNAL_WEIGHTS.values())

if abs(WEIGHT_SUM - 1.0) > 1e-9:
    raise ValueError(f"SIGNAL_WEIGHTS must sum to 1.0, got {WEIGHT_SUM}")

__all__ = ["SIGNAL_WEIGHTS", "WEIGHT_SUM"]
