from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class EngineResult:
    engine: str
    passed: bool
    score: float
    confidence: float
    grade: str
    max_score: float = 100.0
    rule_results: List[Any] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


class BaseEngine(ABC):
    @abstractmethod
    def evaluate(self, stock: Dict[str, Any]) -> EngineResult:
        raise NotImplementedError
