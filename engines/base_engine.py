"""Common engine contract used throughout TrendForge."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(init=False, slots=True)
class EngineResult:
    engine: str
    passed: bool
    score: float
    max_score: float
    confidence: float
    grade: str
    rule_results: list[Any] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def __init__(self, engine=None, passed=False, score=0.0, max_score=100.0, confidence=0.0,
                 grade="D", rule_results=None, reasons=None, warnings=None, metrics=None, *, name=None):
        self.engine = str(name if name is not None else engine or "")
        self.passed = bool(passed)
        self.score = float(score)
        self.max_score = float(max_score)
        self.confidence = float(confidence)
        self.grade = str(grade)
        self.rule_results = list(rule_results or [])
        self.reasons = list(reasons or [])
        self.warnings = list(warnings or [])
        self.metrics = dict(metrics or {})

    def as_dict(self):
        return {"engine": self.engine, "name": self.engine, "passed": self.passed,
                "score": self.score, "confidence": self.confidence, "grade": self.grade,
                "max_score": self.max_score, "rule_results": self.rule_results,
                "reasons": self.reasons, "warnings": self.warnings, "metrics": self.metrics}

class BaseEngine(ABC):
    """Abstract contract for all TrendForge analysis engines."""

    @abstractmethod
    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        raise NotImplementedError


__all__ = ["BaseEngine", "EngineResult"]
