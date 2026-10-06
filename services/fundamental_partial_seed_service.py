"""Safe partial-seed workflow for legacy fundamentals workbooks."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import json

import pandas as pd

from database.repositories.fundamentals_repository import FundamentalsRepository
from providers.fundamental_mapping import extract_fields
from services.fundamental_symbol_resolver import FundamentalSymbolResolver
from services.fundamental_data_manager import FundamentalDataManager
from services.fundamental_import_service import FundamentalFileImportService


class FundamentalPartialSeedService:
    """Preview/apply partial fundamentals without guessing company symbols."""

    SYMBOL_IDENTIFIER_ALIASES = {
        "symbol",
        "nse code",
        "nse_code",
        "ticker",
        "tradingsymbol",
    }
    IDENTIFIER_ALIASES = (
        "symbol",
        "nse code",
        "nse_code",
        "ticker",
        "tradingsymbol",
        "name",
        "stock",
        "company",
        "company name",
    )

    def __init__(
        self,
        manager: FundamentalDataManager | None = None,
        *,
        db_path: str | None = None,
    ) -> None:
        self.manager = manager or FundamentalDataManager(db_path=db_path)
        self.db_path = db_path

    @staticmethod
    def _normalized_column(value: Any) -> str:
        return " ".join(
            str(value or "")
            .strip()
            .lower()
            .replace("_", " ")
            .replace("%", " %")
            .split()
        )

    @classmethod
    def _identifier_column(
        cls,
        frame: pd.DataFrame,
        configured: str | None = None,
    ) -> str:
        normalized = {
            cls._normalized_column(column): str(column)
            for column in frame.columns
        }
        if configured:
            if configured in frame.columns:
                return configured
            matched = normalized.get(cls._normalized_column(configured))
            if matched:
                return matched
            raise ValueError(f"Configured identifier column not found: {configured}")

        for alias in cls.IDENTIFIER_ALIASES:
            matched = normalized.get(cls._normalized_column(alias))
            if matched:
                return matched
        raise ValueError(
            "Legacy fundamentals file needs Symbol/NSE Code/Name/Stock/Company column."
        )

    @staticmethod
    def _load_symbol_map(
        raw: Mapping[str, str] | str | Path | None,
    ) -> dict[str, str]:
        if raw is None:
            return {}
        if isinstance(raw, Mapping):
            return {
                str(name): str(symbol)
                for name, symbol in raw.items()
                if str(name).strip() and str(symbol).strip()
            }

        path = Path(raw).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Symbol map file not found: {path}")

        suffix = path.suffix.lower()
        if suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON symbol map must be an object of name -> symbol")
            return {
                str(name): str(symbol)
                for name, symbol in data.items()
                if str(name).strip() and str(symbol).strip()
            }

        if suffix == ".csv":
            frame = pd.read_csv(path)
        elif suffix in {".xlsx", ".xlsm"}:
            frame = pd.read_excel(path)
        else:
            raise ValueError("Symbol map must be JSON, CSV, XLSX or XLSM")

        normalized = {
            FundamentalPartialSeedService._normalized_column(column): str(column)
            for column in frame.columns
        }
        name_column = (
            normalized.get("name")
            or normalized.get("company")
            or normalized.get("company name")
            or normalized.get("stock")
        )
        symbol_column = (
            normalized.get("symbol")
            or normalized.get("nse code")
            or normalized.get("ticker")
        )
        if not name_column or not symbol_column:
            raise ValueError(
                "Symbol map file needs Name/Company and Symbol/NSE Code columns"
            )
        result: dict[str, str] = {}
        for _, row in frame.iterrows():
            name = row.get(name_column)
            symbol = row.get(symbol_column)
            if pd.isna(name) or pd.isna(symbol):
                continue
            if str(name).strip() and str(symbol).strip():
                result[str(name)] = str(symbol)
        return result

    @staticmethod
    def _candidate_record(
        symbol: str,
        values: Mapping[str, Any],
        *,
        source: str,
        source_file: str,
        as_of: str,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "roce": values.get("roce"),
            "roe": values.get("roe"),
            "sales_growth": values.get("sales_growth"),
            "profit_growth": values.get("profit_growth"),
            "eps_growth": values.get("eps_growth"),
            "debt_to_equity": values.get("debt_equity"),
            "promoter_holding": values.get("promoter_holding"),
            "pledged": values.get("pledged"),
            "source": source,
            "source_file": source_file,
            "as_of": as_of,
        }

    def process_file(
        self,
        path: str | Path,
        *,
        apply: bool = False,
        source: str = "legacy_partial_seed",
        identifier_column: str | None = None,
        field_map: Mapping[str, Any] | str | None = None,
        symbol_map: Mapping[str, str] | str | Path | None = None,
        sheet_name: str | int | None = 0,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        file_path = Path(path).expanduser()
        if not file_path.is_file():
            raise FileNotFoundError(f"Partial seed file not found: {file_path}")

        frame = FundamentalFileImportService._load_frame(
            file_path,
            sheet_name=FundamentalFileImportService._sheet(sheet_name),
        )
        if frame.empty:
            return {
                "status": "empty",
                "mode": "apply" if apply else "preview",
                "file": str(file_path),
                "rows_read": 0,
                "resolved": 0,
                "unresolved": 0,
                "invalid": 0,
                "skipped": 0,
                "applied": 0,
                "resolved_rows": [],
                "unresolved_rows": [],
                "invalid_rows": [],
            }

        identifier_key = self._identifier_column(frame, identifier_column)
        mapping = self._load_symbol_map(symbol_map)
        snapshot_date = as_of or datetime.fromtimestamp(
            file_path.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat()

        from providers.fundamental_mapping import parse_field_map

        parsed_field_map = parse_field_map(field_map)
        identifier_is_symbol = (
            self._normalized_column(identifier_key)
            in {
                self._normalized_column(alias)
                for alias in self.SYMBOL_IDENTIFIER_ALIASES
            }
        )

        resolver = FundamentalSymbolResolver(
            db_path=self.db_path,
            symbol_map=mapping,
        )
        resolved_rows: list[dict[str, Any]] = []
        unresolved_rows: list[dict[str, Any]] = []
        invalid_rows: list[dict[str, Any]] = []
        records: dict[str, dict[str, Any]] = {}
        skipped = 0

        try:
            for row_number, (_, series) in enumerate(frame.iterrows(), start=2):
                payload = series.to_dict()
                identifier = payload.get(identifier_key)
                if pd.isna(identifier) or not str(identifier).strip():
                    skipped += 1
                    continue

                values = extract_fields(payload, parsed_field_map)
                if not values:
                    skipped += 1
                    continue

                if identifier_is_symbol:
                    symbol = FundamentalsRepository.normalize_symbol(identifier)
                    resolution_method = "explicit_symbol_column"
                    resolution_status = "resolved" if symbol else "unresolved"
                    candidates: list[str] = []
                else:
                    resolution = resolver.resolve(identifier)
                    symbol = resolution.symbol
                    resolution_method = resolution.method
                    resolution_status = resolution.status
                    candidates = list(resolution.candidates)

                if not symbol:
                    unresolved_rows.append(
                        {
                            "row": row_number,
                            "identifier": str(identifier),
                            "status": resolution_status,
                            "candidates": candidates,
                            "available_fields": sorted(values),
                        }
                    )
                    continue

                record = self._candidate_record(
                    symbol,
                    values,
                    source=source,
                    source_file=file_path.name,
                    as_of=snapshot_date,
                )
                existing = self.manager.repository.by_symbol(symbol) or {}
                candidate = dict(existing)
                candidate.update(
                    {
                        key: value
                        for key, value in record.items()
                        if value is not None and value != ""
                    }
                )
                before_quality = (
                    self.manager.quality(existing)
                    if existing
                    else {
                        "completeness_pct": 0.0,
                        "missing": list(self.manager.REQUIRED_FIELDS),
                    }
                )
                after_quality = self.manager.quality(candidate)
                if after_quality["invalid"]:
                    invalid_rows.append(
                        {
                            "row": row_number,
                            "identifier": str(identifier),
                            "symbol": symbol,
                            "invalid": after_quality["invalid"],
                            "available_fields": sorted(values),
                        }
                    )
                    continue

                records[symbol] = record
                resolved_rows.append(
                    {
                        "row": row_number,
                        "identifier": str(identifier),
                        "symbol": symbol,
                        "resolution_method": resolution_method,
                        "available_fields": sorted(values),
                        "before_completeness_pct": before_quality["completeness_pct"],
                        "after_completeness_pct": after_quality["completeness_pct"],
                        "remaining_missing": after_quality["missing"],
                    }
                )
        finally:
            resolver.close()

        applied = 0
        if apply and records:
            applied = self.manager.repository.save_many(records.values())

        return {
            "status": "applied" if apply else "preview",
            "mode": "apply" if apply else "preview",
            "file": str(file_path),
            "source": source,
            "as_of": snapshot_date,
            "rows_read": int(len(frame)),
            "resolved": len(resolved_rows),
            "unresolved": len(unresolved_rows),
            "invalid": len(invalid_rows),
            "skipped": skipped,
            "applied": applied,
            "database_records": self.manager.repository.count(),
            "resolved_rows": resolved_rows,
            "unresolved_rows": unresolved_rows,
            "invalid_rows": invalid_rows,
        }

    @staticmethod
    def unresolved_mapping_frame(report: Mapping[str, Any]) -> pd.DataFrame:
        rows = [
            {
                "Name": item.get("identifier"),
                "Symbol": "",
                "Status": item.get("status"),
                "Candidates": ",".join(item.get("candidates") or []),
            }
            for item in report.get("unresolved_rows", [])
        ]
        return pd.DataFrame(rows, columns=["Name", "Symbol", "Status", "Candidates"])


__all__ = ["FundamentalPartialSeedService"]
