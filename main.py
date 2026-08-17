"""TrendForge application entry point."""
from __future__ import annotations

import json

from indicators.indicator_engine import IndicatorEngine
from scanner.scoring_engine import ScoringEngine


def health() -> dict:
    return {
        "status": "healthy",
        "indicator_engine": IndicatorEngine().health(),
        "scoring_engine": ScoringEngine().health(),
    }


def main() -> None:
    print(json.dumps(health(), indent=2, default=str))


if __name__ == "__main__":
    main()
