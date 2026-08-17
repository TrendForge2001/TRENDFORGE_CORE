"""Canonical signal model."""
from dataclasses import dataclass, field


@dataclass(slots=True)
class Signal:
    symbol: str
    signal: str
    confidence: float
    overall_score: float
    entry: float = 0.0
    stoploss: float = 0.0
    target1: float = 0.0
    target2: float = 0.0
    target3: float = 0.0
    risk_reward: float = 0.0
    quantity: int = 0
    strategy: str = "scanner"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
