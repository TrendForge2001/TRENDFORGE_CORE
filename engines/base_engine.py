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
    signal: str = "HOLD"

    def __init__(self, engine=None, passed=False, score=0.0, *args,
                 max_score=None, confidence=None, grade=None, rule_results=None,
                 reasons=None, warnings=None, metrics=None, name=None, signal="HOLD"):
        self.engine = str(name if name is not None else engine or "")
        self.passed = bool(passed)
        self.score = float(score)
        if len(args) >= 3:
            self.max_score = float(args[0] if max_score is None else max_score)
            self.confidence = float(args[1] if confidence is None else confidence)
            self.grade = str(args[2] if grade is None else grade)
        elif len(args) == 2:
            self.max_score = float(100.0 if max_score is None else max_score)
            self.confidence = float(args[0] if confidence is None else confidence)
            self.grade = str(args[1] if grade is None else grade)
        elif len(args) == 1:
            self.max_score = float(args[0] if max_score is None else max_score)
            self.confidence = float(0.0 if confidence is None else confidence)
            self.grade = str("D" if grade is None else grade)
        else:
            self.max_score = float(100.0 if max_score is None else max_score)
            self.confidence = float(0.0 if confidence is None else confidence)
            self.grade = str("D" if grade is None else grade)
        self.rule_results = list(rule_results or [])
        self.reasons = list(reasons or [])
        self.warnings = list(warnings or [])
        self.metrics = dict(metrics or {})
        self.signal = str(signal or "HOLD")

    def as_dict(self):
        return {"engine": self.engine, "name": self.engine, "passed": self.passed,
                "score": self.score, "confidence": self.confidence, "grade": self.grade,
                "max_score": self.max_score, "rule_results": self.rule_results,
                "reasons": self.reasons, "warnings": self.warnings, "metrics": self.metrics, "signal": self.signal}

class BaseEngine(ABC):
    """Abstract contract for all TrendForge analysis engines."""

    @abstractmethod
    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        raise NotImplementedError


__all__ = ["BaseEngine", "EngineResult"]
