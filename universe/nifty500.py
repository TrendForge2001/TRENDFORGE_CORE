"""Canonical NIFTY 500 universe.

The universe layer owns constituent normalization, source metadata and
accounting. It never pads or hardcodes symbols to manufacture a 500 count.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any


@dataclass(frozen=True, slots=True)
class UniverseMember:
    symbol: str
    name: str = ""
    sector: str = ""
    exchange: str = "NSE"
    active: bool = True
    index: str = "NIFTY 500"
    isin: str = ""
    series: str = ""


class Nifty500Universe:
    """Load, normalize, validate and report the canonical NIFTY 500."""

    INDEX_NAME = "NIFTY 500"
    NOMINAL_COMPANY_COUNT = 500
    MIN_SECURITY_COUNT = 500
    MAX_SECURITY_COUNT = 525
    EXPECTED_COUNT = NOMINAL_COMPANY_COUNT

    def __init__(
        self,
        loader: Callable[..., Any] | None = None,
        *,
        max_age_seconds: int = 21600,
    ) -> None:
        self.loader = loader
        self.max_age_seconds = max(0, int(max_age_seconds))
        self._members: tuple[UniverseMember, ...] = ()
        self._source = "not_loaded"
        self._source_url: str | None = None
        self._fetched_at: str | None = None
        self._source_last_modified: str | None = None
        self._source_etag: str | None = None
        self._loaded_at: str | None = None
        self._loaded_at_epoch: float | None = None
        self._invalid_rows = 0
        self._duplicate_symbols: tuple[str, ...] = ()
        self._nominal_company_count = self.NOMINAL_COMPANY_COUNT
        self._minimum_security_count = self.MIN_SECURITY_COUNT
        self._maximum_security_count = self.MAX_SECURITY_COUNT
        self._last_error: str | None = None

    @staticmethod
    def normalize_symbol(value: Any) -> str:
        symbol = str(value or "").strip().upper()
        if symbol.endswith(".NS"):
            symbol = symbol[:-3]
        return symbol.replace(" ", "")

    @classmethod
    def normalize_member(
        cls,
        item: Any,
    ) -> UniverseMember | None:
        if isinstance(item, str):
            symbol = cls.normalize_symbol(item)
            return UniverseMember(symbol=symbol) if symbol else None

        if isinstance(item, Mapping):
            symbol = cls.normalize_symbol(
                item.get("symbol")
                or item.get("SYMBOL")
                or item.get("ticker")
                or item.get("tradingsymbol")
            )
            if not symbol:
                return None
            return UniverseMember(
                symbol=symbol,
                name=str(
                    item.get("name")
                    or item.get("NAME")
                    or item.get("company_name")
                    or ""
                ),
                sector=str(
                    item.get("sector")
                    or item.get("SECTOR")
                    or item.get("industry")
                    or ""
                ),
                exchange=str(item.get("exchange") or "NSE"),
                active=bool(item.get("active", True)),
                isin=str(
                    item.get("isin")
                    or item.get("ISIN")
                    or item.get("isin_code")
                    or ""
                ),
                series=str(item.get("series") or ""),
            )

        return None

    def _apply(
        self,
        source: Iterable[Any],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[UniverseMember]:
        unique: dict[str, UniverseMember] = {}
        duplicates: set[str] = set()
        invalid_rows = 0

        for item in source:
            member = self.normalize_member(item)
            if member is None:
                invalid_rows += 1
                continue
            if not member.active:
                continue
            if member.symbol in unique:
                duplicates.add(member.symbol)
                continue
            unique[member.symbol] = member

        self._members = tuple(
            sorted(unique.values(), key=lambda member: member.symbol)
        )

        meta = dict(metadata or {})
        provider_invalid = int(meta.get("invalid_rows", 0) or 0)
        provider_duplicates = {
            self.normalize_symbol(value)
            for value in (meta.get("duplicate_symbols") or [])
            if self.normalize_symbol(value)
        }

        self._invalid_rows = invalid_rows + provider_invalid
        self._duplicate_symbols = tuple(
            sorted(duplicates | provider_duplicates)
        )
        self._nominal_company_count = int(
            meta.get(
                "nominal_company_count",
                self.NOMINAL_COMPANY_COUNT,
            )
            or self.NOMINAL_COMPANY_COUNT
        )
        self._minimum_security_count = int(
            meta.get(
                "minimum_security_count",
                self.MIN_SECURITY_COUNT,
            )
            or self.MIN_SECURITY_COUNT
        )
        self._maximum_security_count = int(
            meta.get(
                "maximum_security_count",
                self.MAX_SECURITY_COUNT,
            )
            or self.MAX_SECURITY_COUNT
        )
        self._source = str(meta.get("source") or "supplied")
        self._source_url = (
            str(meta.get("source_url"))
            if meta.get("source_url")
            else None
        )
        self._fetched_at = (
            str(meta.get("fetched_at"))
            if meta.get("fetched_at")
            else None
        )
        self._source_last_modified = (
            str(meta.get("source_last_modified"))
            if meta.get("source_last_modified")
            else None
        )
        self._source_etag = (
            str(meta.get("source_etag"))
            if meta.get("source_etag")
            else None
        )
        self._loaded_at = datetime.now(timezone.utc).isoformat()
        self._loaded_at_epoch = time.time()
        self._last_error = None

        return list(self._members)

    def load(
        self,
        constituents: Iterable[Any] | None = None,
    ) -> list[UniverseMember]:
        source = constituents
        metadata: Mapping[str, Any] | None = None

        if source is None:
            return self.refresh()

        if isinstance(source, Mapping):
            metadata = source
            raw_members = source.get("members")
            if not isinstance(raw_members, Iterable):
                raise ValueError(
                    "NIFTY 500 loader payload must contain iterable members"
                )
            source = raw_members

        return self._apply(source, metadata=metadata)

    def refresh(
        self,
        *,
        force_refresh: bool = False,
    ) -> list[UniverseMember]:
        if self.loader is None:
            raise RuntimeError(
                "NIFTY 500 constituent loader is not configured."
            )

        try:
            try:
                payload = self.loader(force_refresh=force_refresh)
            except TypeError:
                payload = self.loader()

            if isinstance(payload, Mapping):
                members = payload.get("members")
                if not isinstance(members, Iterable):
                    raise ValueError(
                        "NIFTY 500 loader payload must contain iterable "
                        "members"
                    )
                return self._apply(members, metadata=payload)

            if not isinstance(payload, Iterable):
                raise ValueError(
                    "NIFTY 500 loader must return an iterable or mapping"
                )

            return self._apply(payload)
        except Exception as exc:
            self._last_error = str(exc)
            raise

    def ensure_loaded(
        self,
        *,
        refresh: bool = False,
    ) -> list[UniverseMember]:
        stale = (
            bool(self._members)
            and self._loaded_at_epoch is not None
            and self.max_age_seconds >= 0
            and time.time() - self._loaded_at_epoch > self.max_age_seconds
        )
        if refresh or not self._members or stale:
            return self.refresh(force_refresh=refresh or stale)
        return list(self._members)

    def symbols(self) -> list[str]:
        return [member.symbol for member in self._members]

    def members(self) -> list[UniverseMember]:
        return list(self._members)

    def contains(self, symbol: str) -> bool:
        return self.normalize_symbol(symbol) in set(self.symbols())

    def report(
        self,
        *,
        include_members: bool = False,
    ) -> dict[str, Any]:
        count = len(self._members)
        age_seconds = (
            max(0.0, time.time() - self._loaded_at_epoch)
            if self._loaded_at_epoch is not None
            else None
        )
        fresh = (
            age_seconds is not None
            and age_seconds <= self.max_age_seconds
        )
        status = (
            "degraded"
            if self._last_error
            else "healthy"
            if self._minimum_security_count
            <= count
            <= self._maximum_security_count
            and not self._duplicate_symbols
            and self._invalid_rows == 0
            and fresh
            else "degraded"
            if self._members
            else "configured"
            if self.loader is not None
            else "not_configured"
        )

        payload: dict[str, Any] = {
            "status": status,
            "index": self.INDEX_NAME,
            "nominal_company_count": self._nominal_company_count,
            "minimum_security_count": self._minimum_security_count,
            "maximum_security_count": self._maximum_security_count,
            "expected_count": self._nominal_company_count,
            "count": count,
            "security_count": count,
            "count_variance": (
                count - self._nominal_company_count
            ),
            "loaded": bool(self._members),
            "source": self._source,
            "source_url": self._source_url,
            "fetched_at": self._fetched_at,
            "source_last_modified": self._source_last_modified,
            "source_etag": self._source_etag,
            "loaded_at": self._loaded_at,
            "age_seconds": (
                round(age_seconds, 3)
                if age_seconds is not None
                else None
            ),
            "max_age_seconds": self.max_age_seconds,
            "fresh": fresh,
            "invalid_rows": self._invalid_rows,
            "duplicate_symbols": list(self._duplicate_symbols),
            "last_error": self._last_error,
        }

        if include_members:
            payload["members"] = [
                {
                    "symbol": member.symbol,
                    "name": member.name,
                    "sector": member.sector,
                    "exchange": member.exchange,
                    "isin": member.isin,
                    "series": member.series,
                }
                for member in self._members
            ]

        return payload

    def health(self) -> dict[str, Any]:
        return self.report(include_members=False)


nifty500_universe = Nifty500Universe()

__all__ = [
    "UniverseMember",
    "Nifty500Universe",
    "nifty500_universe",
]
