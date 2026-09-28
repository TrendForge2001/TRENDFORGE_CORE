"""Common engine contract used throughout TrendForge."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, init=False)
class EngineResult:
    engine: str
    passed: bool
    score: float
    confidence: float
    grade: str
    max_score: float
    rule_results: list[Any]
    reasons: list[str]
    warnings: list[str]
    metrics: dict[str, Any]
    signal: str | None

    def __init__(
        self,
        engine: str | None = None,
        passed: bool = False,
        score: float = 0.0,
        confidence: float = 0.0,
        grade: str = "N/A",
        max_score: float = 100.0,
        rule_results: list[Any] | None = None,
        reasons: list[str] | None = None,
        warnings: list[str] | None = None,
        metrics: dict[str, Any] | None = None,
        signal: str | None = None,
        name: str | None = None,
    ) -> None:
        self.engine = engine or name or "Unknown Engine"
        self.passed = bool(passed)
        self.score = float(score)
        self.confidence = float(confidence)
        self.grade = grade
        self.max_score = float(max_score)
        self.rule_results = list(rule_results or [])
        self.reasons = list(reasons or [])
        self.warnings = list(warnings or [])
        self.metrics = dict(metrics or {})
        self.signal = signal

    @property
    def name(self) -> str:
        return self.engine

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "name": self.engine,
            "passed": self.passed,
            "score": self.score,
            "confidence": self.confidence,
            "grade": self.grade,
            "max_score": self.max_score,
            "rule_results": self.rule_results,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "metrics": self.metrics,
            "signal": self.signal,
        }


class BaseEngine(ABC):
    @abstractmethod
    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        raise NotImplementedError


__all__ = ["BaseEngine", "EngineResult"]
