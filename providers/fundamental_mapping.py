"""Canonical mapping helpers for external fundamental-data providers."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from typing import Any, Mapping

CANONICAL_FIELDS = (
    "roce",
    "roe",
    "sales_growth",
    "profit_growth",
    "eps_growth",
    "debt_equity",
    "promoter_holding",
    "pledged",
)

DEFAULT_ALIASES: dict[str, tuple[str, ...]] = {
    "roce": ("roce", "return_on_capital_employed", "return on capital employed"),
    "roe": ("roe", "return_on_equity", "return on equity"),
    "sales_growth": ("sales_growth", "sales growth", "revenue_growth", "revenue growth"),
    "profit_growth": ("profit_growth", "profit growth", "net_profit_growth", "net profit growth"),
    "eps_growth": ("eps_growth", "eps growth", "earnings_per_share_growth"),
    "debt_equity": ("debt_equity", "debt_to_equity", "debt to equity", "debt/equity"),
    "promoter_holding": ("promoter_holding", "promoter holding", "promoter holding %"),
    "pledged": ("pledged", "pledged holding", "pledged holding %", "pledged percentage"),
}


def parse_field_map(raw: str | Mapping[str, Any] | None) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Fundamental field map must be a JSON object")
    return data


def _walk(payload: Any, path: str) -> Any:
    current = payload
    for part in str(path).split("."):
        if isinstance(current, Mapping):
            if part in current:
                current = current[part]
                continue
            lowered = {str(key).strip().lower(): key for key in current}
            key = lowered.get(part.strip().lower())
            if key is None:
                return None
            current = current[key]
            continue
        return None
    return current


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if value.endswith("%"):
            value = value[:-1].strip()
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def extract_fields(
    payload: Mapping[str, Any],
    field_map: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    mapping = dict(field_map or {})
    values: dict[str, float] = {}
    for field in CANONICAL_FIELDS:
        spec = mapping.get(field)
        candidates: list[tuple[str, float]] = []
        if isinstance(spec, str):
            candidates.append((spec, 1.0))
        elif isinstance(spec, Mapping):
            path = str(spec.get("path") or field)
            try:
                scale = float(spec.get("scale", 1.0))
            except (TypeError, ValueError):
                scale = 1.0
            candidates.append((path, scale))
        else:
            candidates.extend((alias, 1.0) for alias in DEFAULT_ALIASES[field])

        for path, scale in candidates:
            value = _number(_walk(payload, path))
            if value is not None:
                values[field] = value * scale
                break
    return values


def build_snapshot(
    *,
    provider: str,
    symbol: str,
    values: Mapping[str, Any],
    as_of: str | None = None,
    warnings: list[str] | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = {
        field: value
        for field in CANONICAL_FIELDS
        if (value := _number(values.get(field))) is not None
    }
    missing = [field for field in CANONICAL_FIELDS if field not in normalized]
    metadata = {
        "provider": provider,
        "symbol": str(symbol or "").strip().upper(),
        "as_of": as_of or datetime.now(timezone.utc).isoformat(),
        "stale": False,
        "missing": missing,
        "warnings": list(warnings or []),
    }
    if extra_meta:
        metadata.update(dict(extra_meta))
    return {**normalized, "_meta": metadata}


__all__ = [
    "CANONICAL_FIELDS",
    "DEFAULT_ALIASES",
    "build_snapshot",
    "extract_fields",
    "parse_field_map",
]
