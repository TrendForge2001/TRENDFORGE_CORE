"""Common engine contract used throughout TrendForge."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EngineResult:
    engine: str
    passed: bool
    score: float
    confidence: float
    grade: str
    max_score: float = 100.0
    rule_results: list[Any] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "passed": self.passed,
            "score": self.score,
            "confidence": self.confidence,
            "grade": self.grade,
            "max_score": self.max_score,
            "rule_results": self.rule_results,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


class BaseEngine(ABC):
    """Abstract contract for all TrendForge analysis engines."""

    @abstractmethod
    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        raise NotImplementedError


__all__ = ["BaseEngine", "EngineResult"]
