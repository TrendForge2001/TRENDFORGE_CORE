"""TrendForge application entry point using the canonical application factory."""
from __future__ import annotations

import json

from core.application_factory import ApplicationFactory


def health() -> dict:
    """Return health for the complete application construction stack."""
    return ApplicationFactory().health()


def main() -> None:
    print(json.dumps(health(), indent=2, default=str))


if __name__ == "__main__":
    main()
