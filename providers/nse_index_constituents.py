"""Official NSE NIFTY 500 constituent provider.

The source is the NSE-published constituent CSV linked from the NIFTY 500
index page. Network work is explicit; importing this module never performs I/O.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import time
from typing import Any

import requests


NIFTY500_CSV_URL = (
    "https://nsearchives.nseindia.com/content/indices/"
    "ind_nifty500list.csv"
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


@dataclass(frozen=True, slots=True)
class ConstituentParseResult:
    members: tuple[dict[str, Any], ...]
    invalid_rows: int
    duplicate_symbols: tuple[str, ...]


def _normalized_key(value: Any) -> str:
    return "".join(
        ch for ch in str(value or "").strip().lower()
        if ch.isalnum()
    )


def _row_value(row: dict[str, Any], *names: str) -> str:
    normalized = {
        _normalized_key(key): value
        for key, value in row.items()
    }
    for name in names:
        value = normalized.get(_normalized_key(name))
        if value is not None:
            return str(value).strip()
    return ""


def parse_nifty500_csv(csv_text: str) -> ConstituentParseResult:
    """Parse NSE NIFTY 500 CSV without inventing or padding constituents."""

    text = str(csv_text or "").lstrip("\ufeff").strip()
    if not text:
        raise ValueError("NIFTY 500 constituent CSV is empty")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("NIFTY 500 constituent CSV has no header")

    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    invalid_rows = 0

    for row in reader:
        if not isinstance(row, dict):
            invalid_rows += 1
            continue

        symbol = _row_value(
            row,
            "Symbol",
            "Trading Symbol",
            "Tradingsymbol",
        ).upper().replace(" ", "")

        if symbol.endswith(".NS"):
            symbol = symbol[:-3]

        if not symbol:
            invalid_rows += 1
            continue

        if symbol in seen:
            duplicates.append(symbol)
            continue
        seen.add(symbol)

        members.append(
            {
                "symbol": symbol,
                "name": _row_value(
                    row,
                    "Company Name",
                    "Company",
                    "Name",
                ),
                "sector": _row_value(
                    row,
                    "Industry",
                    "Sector",
                ),
                "series": _row_value(row, "Series"),
                "isin": _row_value(
                    row,
                    "ISIN Code",
                    "ISIN",
                ),
                "exchange": "NSE",
                "active": True,
            }
        )

    if not members:
        raise ValueError("NIFTY 500 constituent CSV produced no valid symbols")

    return ConstituentParseResult(
        members=tuple(members),
        invalid_rows=invalid_rows,
        duplicate_symbols=tuple(sorted(set(duplicates))),
    )


class NSEIndexConstituentProvider:
    """Read-only, cached NSE index constituent provider.

    NIFTY 500 is a 500-company index, but the official constituent file can
    contain more than 500 tradable securities when a company has an additional
    eligible security/share class. The official NSE file is therefore treated
    as authoritative for security membership while still failing closed on
    truncated or implausibly large payloads.
    """

    NOMINAL_COMPANY_COUNT = 500
    MIN_SECURITY_COUNT = 500
    MAX_SECURITY_COUNT = 525

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: int = 30,
        cache_ttl: int = 21600,
        nominal_company_count: int = NOMINAL_COMPANY_COUNT,
        min_security_count: int = MIN_SECURITY_COUNT,
        max_security_count: int = MAX_SECURITY_COUNT,
        source_url: str = NIFTY500_CSV_URL,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = max(1, int(timeout))
        self.cache_ttl = max(0, int(cache_ttl))
        self.nominal_company_count = max(
            1,
            int(nominal_company_count),
        )
        self.min_security_count = max(
            self.nominal_company_count,
            int(min_security_count),
        )
        self.max_security_count = max(
            self.min_security_count,
            int(max_security_count),
        )
        self.source_url = str(source_url)

        self._cache: dict[str, Any] | None = None
        self._cached_at: float | None = None
        self._last_success_at: float | None = None
        self._last_error: str | None = None

    def _cache_fresh(self) -> bool:
        return (
            self._cache is not None
            and self._cached_at is not None
            and time.time() - self._cached_at <= self.cache_ttl
        )

    def nifty500(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if not force_refresh and self._cache_fresh():
            return dict(self._cache or {})

        try:
            response = self.session.get(
                self.source_url,
                timeout=self.timeout,
                allow_redirects=True,
            )
            response.raise_for_status()

            content_type = str(
                response.headers.get("content-type") or ""
            ).lower()
            if "html" in content_type:
                raise RuntimeError(
                    "NIFTY 500 source returned HTML instead of CSV"
                )

            parsed = parse_nifty500_csv(response.text)
            count = len(parsed.members)
            if count < self.min_security_count:
                raise RuntimeError(
                    "NIFTY 500 constituent security count below minimum: "
                    f"minimum {self.min_security_count}, received {count}"
                )
            if count > self.max_security_count:
                raise RuntimeError(
                    "NIFTY 500 constituent security count above sanity cap: "
                    f"maximum {self.max_security_count}, received {count}"
                )

            now = time.time()
            payload = {
                "index": "NIFTY 500",
                "source": "NSE_NIFTY500_CSV",
                "source_url": self.source_url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source_last_modified": response.headers.get(
                    "last-modified"
                ),
                "source_etag": response.headers.get("etag"),
                "nominal_company_count": self.nominal_company_count,
                "minimum_security_count": self.min_security_count,
                "maximum_security_count": self.max_security_count,
                "expected_count": self.nominal_company_count,
                "count": count,
                "security_count": count,
                "count_variance": (
                    count - self.nominal_company_count
                ),
                "invalid_rows": parsed.invalid_rows,
                "duplicate_symbols": list(parsed.duplicate_symbols),
                "members": [dict(member) for member in parsed.members],
            }
            self._cache = payload
            self._cached_at = now
            self._last_success_at = now
            self._last_error = None
            return dict(payload)

        except Exception as exc:
            self._last_error = str(exc)
            raise

    def health(self) -> dict[str, Any]:
        cached_count = (
            int(self._cache.get("count", 0))
            if isinstance(self._cache, dict)
            else 0
        )
        if self._last_error:
            status = "degraded"
        elif self._last_success_at is not None:
            status = "runtime_verified"
        else:
            status = "configured"

        return {
            "status": status,
            "provider": self.__class__.__name__,
            "source": "NSE_NIFTY500_CSV",
            "source_url": self.source_url,
            "nominal_company_count": self.nominal_company_count,
            "minimum_security_count": self.min_security_count,
            "maximum_security_count": self.max_security_count,
            "expected_count": self.nominal_company_count,
            "cached_count": cached_count,
            "count_variance": (
                cached_count - self.nominal_company_count
                if cached_count
                else None
            ),
            "cache_ttl_seconds": self.cache_ttl,
            "last_success_at_epoch": self._last_success_at,
            "last_error": self._last_error,
        }


__all__ = [
    "ConstituentParseResult",
    "NIFTY500_CSV_URL",
    "NSEIndexConstituentProvider",
    "parse_nifty500_csv",
]
