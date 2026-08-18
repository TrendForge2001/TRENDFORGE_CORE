"""Normalize provider output into stable engine-facing payload structures."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class EngineInputNormalizer:
    """Keep provider-specific schemas out of the engine layer."""

    FIELDS = ("fundamentals", "corporate_actions", "big_shark", "market_regime", "sector", "risk")

    def normalize(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        for field in self.FIELDS:
            value = result.get(field)
            result[field] = self._normalize_value(value)
        result["symbol"] = str(result.get("symbol", "")).upper()
        return result

    @staticmethod
    def _normalize_value(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, Mapping):
            return dict(value)
        if hasattr(value, "as_dict") and callable(value.as_dict):
            return value.as_dict()
        if hasattr(value, "model_dump") and callable(value.model_dump):
            return value.model_dump()
        return value

    def normalize_many(self, payloads: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        return {symbol: self.normalize(payload) for symbol, payload in payloads.items()}


__all__ = ["EngineInputNormalizer"]
