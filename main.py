"""TrendForge application bootstrap and runtime entry point."""
from __future__ import annotations

import json
from typing import Any

from config.runtime import runtime_health
from indicators.indicator_engine import IndicatorEngine
from scanner.scoring_engine import ScoringEngine
from services.application_service import ApplicationService


def health() -> dict[str, Any]:
    """Return a dependency-safe application health report."""
    components: dict[str, Any] = {}
    for name, factory in {"indicator_engine": IndicatorEngine, "scoring_engine": ScoringEngine}.items():
        try:
            instance = factory()
            checker = getattr(instance, "health", None)
            components[name] = checker() if callable(checker) else {"status": "available"}
        except Exception as exc:
            components[name] = {"status": "unhealthy", "error": str(exc)}
    runtime = runtime_health()
    states = [item.get("status") for item in components.values() if isinstance(item, dict)]
    status = "healthy" if runtime["status"] == "healthy" and "unhealthy" not in states else "degraded"
    return {"status": status, "runtime": runtime, **components}


def main() -> None:
    service = ApplicationService()
    startup = service.start()
    try:
        report = health()
        report["startup"] = startup
        print(json.dumps(report, indent=2, default=str))
    finally:
        service.stop()


if __name__ == "__main__":
    main()
