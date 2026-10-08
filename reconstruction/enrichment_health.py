from __future__ import annotations

from typing import Any

from .enrichment import StockEnricher


REQUIRED_CANONICAL_FIELDS = (
    "fundamentals",
    "corporate_actions",
    "big_shark",
    "sector",
)


def validate_enriched_payload(
    payload: dict[str, Any],
    *,
    required_fields=REQUIRED_CANONICAL_FIELDS,
) -> dict[str, Any]:
    missing = [
        field
        for field in required_fields
        if payload.get(field) is None
    ]
    return {
        "ready": not missing,
        "missing_fields": missing,
        "enrichment_warnings": list(
            payload.get("enrichment_warnings", [])
        ),
        "enrichment_failures": list(
            payload.get("enrichment_failures", [])
        ),
        "provenance": payload.get("enrichment_provenance", {}),
    }


def enrich_and_validate(
    enricher: StockEnricher,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = enricher.enrich(payload)
    merged = enricher.merge(payload, result)
    return merged, validate_enriched_payload(merged)


__all__ = [
    "REQUIRED_CANONICAL_FIELDS",
    "validate_enriched_payload",
    "enrich_and_validate",
]
