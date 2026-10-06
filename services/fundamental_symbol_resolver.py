"""Deterministic symbol resolution for legacy fundamentals files."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from database.repositories.fundamentals_repository import FundamentalsRepository
from database.repositories.instrument_repository import InstrumentRepository


@dataclass(frozen=True, slots=True)
class SymbolResolution:
    input_value: str
    symbol: str | None
    status: str
    method: str | None = None
    candidates: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "input": self.input_value,
            "symbol": self.symbol,
            "status": self.status,
            "method": self.method,
            "candidates": list(self.candidates),
        }


class FundamentalSymbolResolver:
    """Resolve names without fuzzy guessing.

    Priority:
      1. explicit user-supplied map
      2. exact NSE trading symbol present in the instruments table
      3. unique exact NSE instrument-name match
    """

    def __init__(
        self,
        *,
        instrument_repository: InstrumentRepository | None = None,
        db_path: str | None = None,
        symbol_map: Mapping[str, str] | None = None,
    ) -> None:
        self.instruments = instrument_repository or InstrumentRepository(
            db_path=db_path
        )
        self._owns_instruments = instrument_repository is None
        self.symbol_map = {
            self.normalize_name(name): FundamentalsRepository.normalize_symbol(symbol)
            for name, symbol in dict(symbol_map or {}).items()
            if self.normalize_name(name)
            and FundamentalsRepository.normalize_symbol(symbol)
        }

    @staticmethod
    def normalize_name(value: Any) -> str:
        return " ".join(str(value or "").strip().upper().split())

    def resolve(self, value: Any) -> SymbolResolution:
        raw = str(value or "").strip()
        normalized_name = self.normalize_name(raw)
        if not normalized_name:
            return SymbolResolution(
                input_value=raw,
                symbol=None,
                status="unresolved",
            )

        mapped = self.symbol_map.get(normalized_name)
        if mapped:
            return SymbolResolution(
                input_value=raw,
                symbol=mapped,
                status="resolved",
                method="explicit_map",
            )

        symbol_candidate = FundamentalsRepository.normalize_symbol(raw)
        if symbol_candidate:
            row = self.instruments.by_symbol(symbol_candidate, exchange="NSE")
            if row is not None:
                return SymbolResolution(
                    input_value=raw,
                    symbol=FundamentalsRepository.normalize_symbol(
                        row["tradingsymbol"]
                    ),
                    status="resolved",
                    method="instrument_symbol_exact",
                )

        matches = self.instruments.exact_name_matches(raw, exchange="NSE")
        symbols = tuple(
            sorted(
                {
                    FundamentalsRepository.normalize_symbol(row["tradingsymbol"])
                    for row in matches
                    if row.get("tradingsymbol")
                }
            )
        )
        if len(symbols) == 1:
            return SymbolResolution(
                input_value=raw,
                symbol=symbols[0],
                status="resolved",
                method="instrument_name_exact",
            )
        if len(symbols) > 1:
            return SymbolResolution(
                input_value=raw,
                symbol=None,
                status="ambiguous",
                candidates=symbols,
            )
        return SymbolResolution(
            input_value=raw,
            symbol=None,
            status="unresolved",
        )

    def close(self) -> None:
        if self._owns_instruments:
            self.instruments.close()


__all__ = ["FundamentalSymbolResolver", "SymbolResolution"]
