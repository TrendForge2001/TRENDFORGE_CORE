"""TrendForge application bootstrap and runtime health entry point."""
from __future__ import annotations

import json
from typing import Any

from config.runtime import runtime_health
from indicators.indicator_engine import IndicatorEngine
from scanner.scoring_engine import ScoringEngine


def health() -> dict[str, Any]:
    """Return a dependency-safe application health report."""
    components: dict[str, Any] = {}
    for name, factory in {
        "indicator_engine": IndicatorEngine,
        "scoring_engine": ScoringEngine,
    }.items():
        try:
            instance = factory()
            checker = getattr(instance, "health", None)
            components[name] = checker() if callable(checker) else {"status": "available"}
        except Exception as exc:
            components[name] = {"status": "unhealthy", "error": str(exc)}

    runtime = runtime_health()
    component_states = [item.get("status") for item in components.values() if isinstance(item, dict)]
    status = "healthy" if runtime["status"] == "healthy" and all(s != "unhealthy" for s in component_states) else "degraded"
    return {"status": status, "runtime": runtime, **components}


def main() -> None:
    print(json.dumps(health(), indent=2, default=str))


if __name__ == "__main__":
    main()
