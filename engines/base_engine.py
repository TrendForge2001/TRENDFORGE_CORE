"""Common engine contract used throughout TrendForge."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EngineResult:
    """Normalized result returned by every analysis engine."""
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

    def __post_init__(self) -> None:
        self.score = float(self.score or 0.0)
        self.max_score = max(0.0, float(self.max_score or 0.0))
        self.confidence = max(0.0, min(100.0, float(self.confidence or 0.0)))
        self.grade = str(self.grade or "UNKNOWN")

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "passed": bool(self.passed),
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

    NAME = "BASE_ENGINE"
    mandatory = False

    @abstractmethod
    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        raise NotImplementedError


__all__ = ["BaseEngine", "EngineResult"]
