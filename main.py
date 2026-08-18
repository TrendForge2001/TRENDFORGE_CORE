"""TrendForge application entry point and canonical pipeline health check."""
from __future__ import annotations

import json

from engines.engine_orchestrator import EngineOrchestrator
from indicators.indicator_engine import IndicatorEngine
from scanner.scoring_engine import ScoringEngine


def health() -> dict:
    """Return application health without bypassing the rebuilt engine pipeline."""
    orchestrator = EngineOrchestrator()
    return {
        "status": "healthy",
        "engine_orchestrator": orchestrator.health(),
        "indicator_engine": IndicatorEngine().health(),
        "scoring_engine": ScoringEngine().health(),
    }


def main() -> None:
    print(json.dumps(health(), indent=2, default=str))


if __name__ == "__main__":
    main()
