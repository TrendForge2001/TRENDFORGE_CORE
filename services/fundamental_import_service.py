"""CSV/XLSX -> canonical fundamentals -> SQLite import service."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import json

import pandas as pd

from database.repositories.fundamentals_repository import FundamentalsRepository
from providers.fundamental_mapping import (
    CANONICAL_FIELDS,
    extract_fields,
    parse_field_map,
)


class FundamentalFileImportService:
    """Import periodic Screener/Tijori/manual exports into SQLite once."""

    SYMBOL_ALIASES = (
        "symbol",
        "nse code",
        "nse_code",
        "nse",
        "ticker",
        "company code",
        "code",
    )
    SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".xlsm")

    def __init__(
        self,
        repository: FundamentalsRepository | None = None,
        *,
        db_path: str | None = None,
    ) -> None:
        self.repository = repository or FundamentalsRepository(db_path=db_path)

    @staticmethod
    def _normalize_column(value: Any) -> str:
        return " ".join(
            str(value or "")
            .strip()
            .lower()
            .replace("_", " ")
            .replace("%", " %")
            .split()
        )

    @staticmethod
    def _normalize_symbol(value: Any) -> str:
        return FundamentalsRepository.normalize_symbol(value)

    @classmethod
    def _load_frame(
        cls,
        path: Path,
        *,
        sheet_name: str | int | None = 0,
    ) -> pd.DataFrame:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(path)
        if suffix in {".xlsx", ".xlsm"}:
            return pd.read_excel(path, sheet_name=sheet_name)
        raise ValueError(
            "Unsupported fundamentals file. Use CSV, XLSX or XLSM."
        )

    @classmethod
    def _symbol_column(
        cls,
        frame: pd.DataFrame,
        configured: str | None = None,
    ) -> str:
        normalized = {
            cls._normalize_column(column): str(column)
            for column in frame.columns
        }
        if configured:
            if configured in frame.columns:
                return configured
            match = normalized.get(cls._normalize_column(configured))
            if match:
                return match
            raise ValueError(
                f"Configured fundamental symbol column not found: {configured}"
            )
        for alias in cls.SYMBOL_ALIASES:
            match = normalized.get(cls._normalize_column(alias))
            if match:
                return match
        raise ValueError(
            "Fundamental file needs a symbol/NSE column or FUNDAMENTALS_SYMBOL_COLUMN."
        )

    @staticmethod
    def _as_of(path: Path, explicit: str | None) -> str:
        if explicit:
            return explicit
        return datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat()

    @staticmethod
    def _sheet(value: str | int | None) -> str | int | None:
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if text.isdigit():
            return int(text)
        return text

    def import_file(
        self,
        path: str | Path,
        *,
        source: str = "manual_file",
        symbol_column: str | None = None,
        field_map: str | Mapping[str, Any] | None = None,
        sheet_name: str | int | None = 0,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        file_path = Path(path).expanduser()
        if not file_path.is_file():
            raise FileNotFoundError(f"Fundamentals import file not found: {file_path}")
        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                "Unsupported fundamentals file. Use CSV, XLSX or XLSM."
            )

        mapping = parse_field_map(field_map)
        frame = self._load_frame(
            file_path,
            sheet_name=self._sheet(sheet_name),
        )
        if frame.empty:
            return {
                "status": "empty",
                "file": str(file_path),
                "source": source,
                "rows_read": 0,
                "imported": 0,
                "incomplete": 0,
                "skipped": 0,
            }

        symbol_key = self._symbol_column(frame, symbol_column)
        snapshot_date = self._as_of(file_path, as_of)
        by_symbol: dict[str, dict[str, Any]] = {}
        skipped = 0
        incomplete = 0

        for _, series in frame.iterrows():
            row = series.to_dict()
            symbol = self._normalize_symbol(row.get(symbol_key))
            if not symbol or symbol in {"NAN", "NONE"}:
                skipped += 1
                continue

            values = extract_fields(row, mapping)
            if not values:
                skipped += 1
                continue

            missing = [
                field for field in CANONICAL_FIELDS
                if field not in values
            ]
            if missing:
                incomplete += 1

            record = {
                "symbol": symbol,
                "roce": values.get("roce"),
                "roe": values.get("roe"),
                "sales_growth": values.get("sales_growth"),
                "profit_growth": values.get("profit_growth"),
                "eps_growth": values.get("eps_growth"),
                "debt_to_equity": values.get("debt_equity"),
                "promoter_holding": values.get("promoter_holding"),
                "pledged": values.get("pledged"),
                "source": str(source or "manual_file"),
                "source_file": file_path.name,
                "as_of": snapshot_date,
            }
            by_symbol[symbol] = record

        imported = self.repository.save_many(by_symbol.values())
        return {
            "status": "imported",
            "file": str(file_path),
            "source": str(source or "manual_file"),
            "as_of": snapshot_date,
            "rows_read": int(len(frame)),
            "unique_symbols": len(by_symbol),
            "imported": imported,
            "incomplete": incomplete,
            "skipped": skipped,
            "field_map": mapping,
        }


__all__ = ["FundamentalFileImportService"]
