"""Primary/fallback composition for fundamental-data providers."""
from __future__ import annotations

from typing import Any, Mapping

from providers.fundamental_mapping import CANONICAL_FIELDS, build_snapshot


class CompositeFundamentalProvider:
    NAME = "CompositeFundamentalProvider"

    def __init__(self, providers: list[Any] | tuple[Any, ...]):
        self.providers = [provider for provider in providers if provider is not None]

    @staticmethod
    def _call(provider: Any, symbol: str) -> Any:
        method = getattr(provider, "get", None)
        if callable(method):
            return method(symbol)
        method = getattr(provider, "get_fundamentals", None)
        if callable(method):
            return method(symbol)
        raise TypeError(
            f"{provider.__class__.__name__} must implement get() or get_fundamentals()"
        )

    def get(self, symbol: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        symbol = str(symbol or "").strip().upper()
        if not symbol:
            raise ValueError("Symbol is required for fundamental enrichment")

        values: dict[str, Any] = {}
        field_sources: dict[str, str] = {}
        source_meta: list[dict[str, Any]] = []
        warnings: list[str] = []
        errors: list[str] = []

        for provider in self.providers:
            name = getattr(provider, "NAME", provider.__class__.__name__)
            try:
                data = self._call(provider, symbol)
            except Exception as exc:
                errors.append(f"{name}:{exc}")
                continue
            if not isinstance(data, Mapping):
                continue

            meta = data.get("_meta")
            meta = dict(meta) if isinstance(meta, Mapping) else {}
            source_meta.append(
                {
                    "provider": name,
                    "stale": bool(meta.get("stale", False)),
                    "missing": list(meta.get("missing") or []),
                    "warnings": list(meta.get("warnings") or []),
                }
            )
            warnings.extend(
                f"{name}:{warning}"
                for warning in (meta.get("warnings") or [])
            )
            if meta.get("stale") is True:
                continue

            for field in CANONICAL_FIELDS:
                if field not in values and data.get(field) is not None:
                    values[field] = data[field]
                    field_sources[field] = name

            if all(field in values for field in CANONICAL_FIELDS):
                break

        if not values:
            if errors:
                raise RuntimeError(" | ".join(errors))
            return None

        if errors:
            warnings.extend(f"provider_error:{error}" for error in errors)

        return build_snapshot(
            provider=self.NAME,
            symbol=symbol,
            values=values,
            warnings=list(dict.fromkeys(warnings)),
            extra_meta={
                "sources": source_meta,
                "field_sources": field_sources,
                "provider_errors": errors,
            },
        )

    def get_fundamentals(self, symbol: str) -> dict[str, Any] | None:
        return self.get(symbol)

    def health(self) -> dict[str, Any]:
        providers = []
        for provider in self.providers:
            name = getattr(provider, "NAME", provider.__class__.__name__)
            health = getattr(provider, "health", None)
            if callable(health):
                try:
                    status = health()
                except Exception as exc:
                    status = {"status": "degraded", "error": str(exc)}
            else:
                status = {"status": "configured"}
            providers.append({"provider": name, **status})
        return {
            "status": "configured" if self.providers else "not_configured",
            "provider": self.NAME,
            "providers": providers,
            "network_probe": False,
        }


__all__ = ["CompositeFundamentalProvider"]
