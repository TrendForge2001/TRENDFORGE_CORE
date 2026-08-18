"""Shared engine result types.

EngineResult is defined once in engines.base_engine.  This module retains the
RuleResult type for model-layer consumers while re-exporting that canonical
engine result contract.
"""

from dataclasses import dataclass
from typing import Any

from engines.base_engine import EngineResult


@dataclass(slots=True)
class RuleResult:
    name: str
    score: float
    max_score: float
    passed: bool
    reason: str
    warning: str = ""
    value: Any = None


__all__ = ["RuleResult", "EngineResult"]
