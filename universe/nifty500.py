"""Canonical NIFTY 500 universe provider.

The universe layer deliberately owns constituent discovery and normalization.
It does not embed a stale 500-symbol snapshot; callers can supply a refreshed
constituent payload or use a configured provider callable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class UniverseMember:
    symbol: str
    name: str = ""
    sector: str = ""
    exchange: str = "NSE"
    active: bool = True
    index: str = "NIFTY 500"


class Nifty500Universe:
    """Load, normalize and validate the NIFTY 500 constituent universe."""

    INDEX_NAME = "NIFTY 500"

    def __init__(self, loader: Callable[[], Iterable[Any]] | None = None) -> None:
        self.loader = loader
        self._members: tuple[UniverseMember, ...] = ()

    @staticmethod
    def normalize_symbol(value: Any) -> str:
        symbol = str(value or "").strip().upper()
        if symbol.endswith(".NS"):
            symbol = symbol[:-3]
        return symbol.replace(" ", "")

    @classmethod
    def normalize_member(cls, item: Any) -> UniverseMember | None:
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
                name=str(item.get("name") or item.get("NAME") or ""),
                sector=str(item.get("sector") or item.get("SECTOR") or ""),
                exchange=str(item.get("exchange") or "NSE"),
                active=bool(item.get("active", True)),
            )

        return None

    def load(self, constituents: Iterable[Any] | None = None) -> list[UniverseMember]:
        source = constituents
        if source is None:
            if self.loader is None:
                raise RuntimeError(
                    "NIFTY 500 constituent loader is not configured. "
                    "Provide constituents or a loader callable."
                )
            source = self.loader()

        unique: dict[str, UniverseMember] = {}
        for item in source:
            member = self.normalize_member(item)
            if member is not None and member.active:
                unique.setdefault(member.symbol, member)

        self._members = tuple(sorted(unique.values(), key=lambda m: m.symbol))
        return list(self._members)

    def symbols(self) -> list[str]:
        return [member.symbol for member in self._members]

    def members(self) -> list[UniverseMember]:
        return list(self._members)

    def contains(self, symbol: str) -> bool:
        return self.normalize_symbol(symbol) in set(self.symbols())

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self._members else "empty",
            "index": self.INDEX_NAME,
            "count": len(self._members),
            "loaded": bool(self._members),
        }


nifty500_universe = Nifty500Universe()

__all__ = ["UniverseMember", "Nifty500Universe", "nifty500_universe"]
