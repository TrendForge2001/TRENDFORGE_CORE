from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class RuleResult:
    name: str
    score: float
    max_score: float
    passed: bool
    reason: str
    warning: str = ""
    value: Any = None


@dataclass
class EngineResult:
    engine: str
    score: float
    passed: bool
    confidence: float
    grade: str
    max_score: float = 100.0
    rule_results: List[RuleResult] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
