"""Legacy result aggregation helper.

Engine execution and canonical score aggregation belong to EngineOrchestrator.
This helper remains only for callers that need presentation-level aggregation of
already-produced EngineResult objects.
"""

from __future__ import annotations

from typing import Any, Mapping


class ResultAggregator:
    """Aggregate existing engine results without executing any engine."""

    def aggregate(self, results: Mapping[str, Any] | None) -> dict[str, Any]:
        if not results:
            return {"score": 0.0, "confidence": 0.0, "reasons": []}

        values = list(results.values())
        total = sum(float(getattr(result, "score", 0.0) or 0.0) for result in values)
        confidence = sum(
            float(getattr(result, "confidence", 0.0) or 0.0) for result in values
        ) / len(values)

        reasons: list[Any] = []
        for result in values:
            reasons.extend(getattr(result, "reasons", None) or [])

        return {
            "score": total,
            "confidence": confidence,
            "reasons": reasons[:20],
        }


__all__ = ["ResultAggregator"]
