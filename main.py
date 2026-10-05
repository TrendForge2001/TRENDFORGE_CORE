"""TrendForge thin runtime entry point."""
from __future__ import annotations

import json
from typing import Any

from config.runtime import runtime_health
from core.application_factory import ApplicationFactory, build_application_factory


def _status(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    return str(payload.get("status", "unknown")).lower()


def health() -> dict[str, Any]:
    """Return deployment-facing health from the canonical composition root.

    ``ApplicationFactory.health()`` keeps its strict runtime-readiness semantics,
    where merely configured components are reported as degraded overall.  The
    top-level process health is intentionally deployment-safe: optional broker
    credentials are not required for the scanner/API process to be healthy.
    """
    report = dict(build_application_factory().health())
    runtime = runtime_health()

    database_status = _status(report.get("database"))
    market_status = _status(report.get("market_data"))
    scanner_status = _status(report.get("scanner"))

    database_ready = database_status in {"ready", "initialized"}
    market_ready = market_status in {"healthy", "ok", "configured"}
    scanner_ready = scanner_status in {"healthy", "ok", "configured"}
    runtime_ready = _status(runtime) in {"healthy", "ok"}

    report["status"] = (
        "healthy"
        if runtime_ready and database_ready and market_ready and scanner_ready
        else "degraded"
    )
    report["runtime"] = runtime

    # Compatibility component summaries for callers that consumed the legacy
    # top-level health contract. Execution still belongs to the canonical
    # FullScannerPipeline owned by ApplicationFactory.
    report["indicator_engine"] = {
        "status": "configured" if scanner_ready else scanner_status,
        "source": "canonical_pipeline",
    }
    report["scoring_engine"] = {
        "status": scanner_status,
        "source": "canonical_pipeline",
    }
    return report


def main() -> None:
    application = build_application_factory()
    print(json.dumps(health(), indent=2, default=str))


if __name__ == "__main__":
    main()
