"""Official NSE broad-market constituent loader for R71.5 validation.

Supports NIFTY 100, NIFTY 200 and NIFTY 500 from NSE-published CSV files.
The provider is read-only, cached, and never manufactures missing members.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any

import requests

from providers.nse_index_constituents import (
    DEFAULT_HEADERS,
    parse_nifty500_csv,
)


@dataclass(frozen=True, slots=True)
class BroadMarketIndexConfig:
    name: str
    source: str
    source_url: str
    nominal_count: int
    minimum_count: int
    maximum_count: int


INDEX_CONFIGS: dict[str, BroadMarketIndexConfig] = {
    "NIFTY 100": BroadMarketIndexConfig(
        name="NIFTY 100",
        source="NSE_NIFTY100_CSV",
        source_url=(
            "https://nsearchives.nseindia.com/content/indices/"
            "ind_nifty100list.csv"
        ),
        nominal_count=100,
        minimum_count=100,
        maximum_count=110,
    ),
    "NIFTY 200": BroadMarketIndexConfig(
        name="NIFTY 200",
        source="NSE_NIFTY200_CSV",
        source_url=(
            "https://nsearchives.nseindia.com/content/indices/"
            "ind_nifty200list.csv"
        ),
        nominal_count=200,
        minimum_count=200,
        maximum_count=215,
    ),
    "NIFTY 500": BroadMarketIndexConfig(
        name="NIFTY 500",
        source="NSE_NIFTY500_CSV",
        source_url=(
            "https://nsearchives.nseindia.com/content/indices/"
            "ind_nifty500list.csv"
        ),
        nominal_count=500,
        minimum_count=500,
        maximum_count=525,
    ),
}


def normalize_index_name(value: str) -> str:
    compact = " ".join(str(value or "").strip().upper().replace("_", " ").split())
    aliases = {
        "NIFTY100": "NIFTY 100",
        "NIFTY 100": "NIFTY 100",
        "100": "NIFTY 100",
        "NIFTY200": "NIFTY 200",
        "NIFTY 200": "NIFTY 200",
        "200": "NIFTY 200",
        "NIFTY500": "NIFTY 500",
        "NIFTY 500": "NIFTY 500",
        "500": "NIFTY 500",
    }
    resolved = aliases.get(compact)
    if resolved is None:
        raise ValueError("index must be NIFTY 100, NIFTY 200 or NIFTY 500")
    return resolved


class NSEBroadMarketConstituentProvider:
    """Fetch and cache official NIFTY 100/200/500 constituent CSVs."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: int = 30,
        cache_ttl: int = 21600,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = max(1, int(timeout))
        self.cache_ttl = max(0, int(cache_ttl))
        self._cache: dict[str, dict[str, Any]] = {}
        self._cached_at: dict[str, float] = {}
        self._last_error: dict[str, str] = {}

    def _fresh(self, index_name: str) -> bool:
        stamp = self._cached_at.get(index_name)
        return (
            index_name in self._cache
            and stamp is not None
            and time.time() - stamp <= self.cache_ttl
        )

    def load(
        self,
        index_name: str,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        name = normalize_index_name(index_name)
        config = INDEX_CONFIGS[name]
        if not force_refresh and self._fresh(name):
            return dict(self._cache[name])

        try:
            # Both sources are operated by NSE Indices.  The archive host
            # occasionally rejects cloud IPs; use the official indices host
            # before falling back to our last validated snapshot.
            filename = config.source_url.rsplit("/", 1)[-1]
            sources = (
                config.source_url,
                f"https://www.niftyindices.com/IndexConstituent/{filename}",
            )
            last_source_error = None
            for source_url in sources:
                try:
                    response = self.session.get(
                        source_url,
                        timeout=min(self.timeout, 12),
                        allow_redirects=True,
                    )
                    response.raise_for_status()
                    content_type = str(
                        response.headers.get("content-type") or ""
                    ).lower()
                    if "html" in content_type:
                        raise RuntimeError(
                            f"{name} source returned HTML instead of CSV"
                        )
                    parsed = parse_nifty500_csv(response.text)
                    count = len(parsed.members)
                    if count < config.minimum_count:
                        raise RuntimeError(
                            f"{name} security count below minimum: "
                            f"{config.minimum_count}, received {count}"
                        )
                    if count > config.maximum_count:
                        raise RuntimeError(
                            f"{name} security count above sanity cap: "
                            f"{config.maximum_count}, received {count}"
                        )
                    break
                except Exception as source_exc:
                    last_source_error = source_exc
            else:
                raise RuntimeError(
                    f"{name} official NSE constituent downloads failed: "
                    f"{type(last_source_error).__name__}: {last_source_error}"
                )

            now = time.time()
            payload = {
                "index": name,
                "source": config.source,
                "source_url": source_url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source_last_modified": response.headers.get("last-modified"),
                "source_etag": response.headers.get("etag"),
                "nominal_company_count": config.nominal_count,
                "minimum_security_count": config.minimum_count,
                "maximum_security_count": config.maximum_count,
                "expected_count": config.nominal_count,
                "count": count,
                "security_count": count,
                "count_variance": count - config.nominal_count,
                "invalid_rows": parsed.invalid_rows,
                "duplicate_symbols": list(parsed.duplicate_symbols),
                "members": [dict(member) for member in parsed.members],
            }
            self._cache[name] = payload
            self._cached_at[name] = now
            self._last_error.pop(name, None)
            return dict(payload)
        except Exception as exc:
            self._last_error[name] = str(exc)
            raise

    def load_all(
        self,
        *,
        force_refresh: bool = False,
    ) -> dict[str, dict[str, Any]]:
        return {
            name: self.load(name, force_refresh=force_refresh)
            for name in ("NIFTY 100", "NIFTY 200", "NIFTY 500")
        }

    def health(self) -> dict[str, Any]:
        indexes: dict[str, Any] = {}
        for name, config in INDEX_CONFIGS.items():
            cached = self._cache.get(name) or {}
            error = self._last_error.get(name)
            indexes[name] = {
                "status": (
                    "degraded"
                    if error
                    else "runtime_verified"
                    if cached
                    else "configured"
                ),
                "source": config.source,
                "source_url": config.source_url,
                "cached_count": int(cached.get("count") or 0),
                "last_error": error,
            }
        return {
            "status": (
                "degraded"
                if any(item["status"] == "degraded" for item in indexes.values())
                else "runtime_verified"
                if all(item["status"] == "runtime_verified" for item in indexes.values())
                else "configured"
            ),
            "provider": self.__class__.__name__,
            "indexes": indexes,
            "cache_ttl_seconds": self.cache_ttl,
        }


__all__ = [
    "BroadMarketIndexConfig",
    "INDEX_CONFIGS",
    "NSEBroadMarketConstituentProvider",
    "normalize_index_name",
]
