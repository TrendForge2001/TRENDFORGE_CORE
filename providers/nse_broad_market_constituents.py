"""Official NSE broad-market constituent loader for R71.5 validation.

Supports NIFTY 100, NIFTY 200 and NIFTY 500 from NSE-published CSV files.
The provider is read-only, cached, and never manufactures missing members.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any
from uuid import uuid4

import requests

from providers.nse_index_constituents import (
    DEFAULT_HEADERS,
    parse_nifty500_csv,
)

_LOG = logging.getLogger("trendforge.nse.constituents")
_REFRESH_UNAVAILABLE = "NSE constituent refresh temporarily unavailable"
_FAILURE_COOLDOWN_SECONDS = 5.0


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
        cache_dir: str | Path | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = max(1, int(timeout))
        self.cache_ttl = max(0, int(cache_ttl))
        self._cache: dict[str, dict[str, Any]] = {}
        self._cached_at: dict[str, float] = {}
        self._last_error: dict[str, str] = {}
        self._last_error_reference: dict[str, str] = {}
        self._failure_retry_after: dict[str, float] = {}
        self._load_locks = {name: threading.Lock() for name in INDEX_CONFIGS}
        self.cache_dir = Path(
            cache_dir or os.getenv("TRENDFORGE_INDEX_CACHE_DIR", "/tmp/trendforge_index_cache")
        )

    def _fresh(self, index_name: str) -> bool:
        stamp = self._cached_at.get(index_name)
        return (
            index_name in self._cache
            and stamp is not None
            and time.time() - stamp <= self.cache_ttl
        )

    def _cache_file(self, name: str) -> Path:
        return self.cache_dir / (name.lower().replace(" ", "_") + ".json")

    def _saved_members(self, name: str) -> dict[str, Any] | None:
        """Reuse only a previously validated official NSE snapshot."""
        try:
            payload = json.loads(
                self._cache_file(name).read_text(encoding="utf-8")
            )
            config = INDEX_CONFIGS[name]
            members = payload.get("members")
            if (
                payload.get("source") != config.source
                or not isinstance(members, list)
                or not config.minimum_count <= len(members) <= config.maximum_count
            ):
                return None
            symbols = [
                str(row.get("symbol") or "").strip().upper()
                for row in members
            ]
            if not all(symbols) or len(set(symbols)) != len(symbols):
                return None
            return payload
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def _packaged_members(self, name: str) -> dict[str, Any] | None:
        """Return a validated repository snapshot when live NSE is unreachable.

        The package fallback is intentionally limited to indexes for which a
        reviewed snapshot is shipped with the application. Live NSE and the
        last validated runtime cache always take precedence.
        """
        filename = {
            "NIFTY 100": "nifty100_constituents_snapshot.json",
        }.get(name)
        if not filename:
            return None
        try:
            path = Path(__file__).resolve().parent / "data" / filename
            payload = json.loads(path.read_text(encoding="utf-8"))
            config = INDEX_CONFIGS[name]
            members = payload.get("members")
            if (
                payload.get("index") != name
                or payload.get("source") != config.source
                or not isinstance(members, list)
                or not config.minimum_count <= len(members) <= config.maximum_count
            ):
                return None
            symbols = [
                str(row.get("symbol") or "").strip().upper()
                for row in members
                if isinstance(row, dict)
            ]
            if (
                len(symbols) != len(members)
                or not all(symbols)
                or len(set(symbols)) != len(symbols)
            ):
                return None
            snapshot = dict(payload)
            snapshot.update(
                {
                    "index": name,
                    "source": config.source,
                    "nominal_company_count": config.nominal_count,
                    "minimum_security_count": config.minimum_count,
                    "maximum_security_count": config.maximum_count,
                    "expected_count": config.nominal_count,
                    "count": len(members),
                    "security_count": len(members),
                    "count_variance": len(members) - config.nominal_count,
                    "members": [dict(row) for row in members],
                    "stale": True,
                    "snapshot_storage": "package",
                }
            )
            return snapshot
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            return None

    def _save_members(self, name: str, payload: dict[str, Any]) -> None:
        """Cache validated NSE constituents atomically (instance-local only)."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._cache_file(name)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def load(
        self,
        index_name: str,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        name = normalize_index_name(index_name)
        # Recheck the cache inside the lock: concurrent initial requests share
        # one fetch, including stale fallback results and uncached failures.
        with self._load_locks[name]:
            return self._load(name, force_refresh=force_refresh)

    def _load(self, name: str, *, force_refresh: bool) -> dict[str, Any]:
        config = INDEX_CONFIGS[name]
        if not force_refresh and self._fresh(name):
            return dict(self._cache[name])
        if (
            not force_refresh
            and time.monotonic() < self._failure_retry_after.get(name, 0.0)
        ):
            reference = self._last_error_reference[name]
            raise RuntimeError(f"{_REFRESH_UNAVAILABLE} (reference {reference})") from None

        try:
            # Both sources are operated by NSE Indices.  The archive host
            # occasionally rejects cloud IPs; use the official indices host
            # before falling back to our last validated snapshot.
            filename = config.source_url.rsplit("/", 1)[-1]
            sources = (
                config.source_url,
                f"https://www.niftyindices.com/IndexConstituent/{filename}",
            )
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
                except Exception:
                    continue
            else:
                raise RuntimeError(
                    f"{name} official NSE constituent downloads failed"
                ) from None

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
            self._last_error_reference.pop(name, None)
            self._failure_retry_after.pop(name, None)
            self._save_members(name, payload)
            return dict(payload)
        except Exception as exc:
            reference = uuid4().hex[:12]
            self._last_error[name] = _REFRESH_UNAVAILABLE
            self._last_error_reference[name] = reference
            _LOG.warning(
                "nse_constituents_unavailable index=%s exception_type=%s reference=%s",
                name, type(exc).__name__, reference,
            )
            cached = (
                self._cache.get(name)
                or self._saved_members(name)
                or self._packaged_members(name)
            )
            if cached:
                stale = dict(cached)
                stale["stale"] = True
                if stale.get("snapshot_storage") == "package":
                    try:
                        snapshot_as_of = date.fromisoformat(
                            str(stale.get("snapshot_as_of"))
                        ).isoformat()
                    except ValueError:
                        snapshot_as_of = "unknown"
                    stale["source_warning"] = (
                        f"Live NSE refresh unavailable; using bundled {name} "
                        f"constituent snapshot as of {snapshot_as_of}. "
                        f"Reference {reference}."
                    )
                else:
                    stale["source_warning"] = (
                        f"Live NSE refresh unavailable; using the last validated "
                        f"{name} constituent snapshot. Reference {reference}."
                    )
                self._cache[name] = stale
                self._cached_at[name] = time.time()
                self._failure_retry_after.pop(name, None)
                return dict(stale)
            self._failure_retry_after[name] = (
                time.monotonic() + _FAILURE_COOLDOWN_SECONDS
            )
            raise RuntimeError(f"{_REFRESH_UNAVAILABLE} (reference {reference})") from None

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
                "last_error_reference": self._last_error_reference.get(name),
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
