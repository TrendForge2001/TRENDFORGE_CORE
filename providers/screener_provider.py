"""Screener.in premium CSV-export fundamental provider.

Screener does not provide an API. This provider reads a user-generated premium
CSV export from a local path or a user-controlled URL; it does not scrape
Screener pages or automate login.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Mapping
import os

import pandas as pd
import requests

from providers.fundamental_mapping import build_snapshot, extract_fields, parse_field_map


class ScreenerProvider:
    NAME = "ScreenerProvider"

    SYMBOL_ALIASES = (
        "symbol",
        "nse code",
        "nse_code",
        "nse",
        "ticker",
        "company code",
    )

    def __init__(
        self,
        *,
        export_path: str | None = None,
        export_url: str | None = None,
        symbol_column: str | None = None,
        field_map: str | Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        session: Any | None = None,
    ) -> None:
        self.export_path = (
            export_path
            if export_path is not None
            else os.getenv("SCREENER_EXPORT_PATH")
        )
        self.export_url = (
            export_url
            if export_url is not None
            else os.getenv("SCREENER_EXPORT_URL")
        )
        self.symbol_column = (
            symbol_column
            if symbol_column is not None
            else os.getenv("SCREENER_SYMBOL_COLUMN")
        )
        raw_map = field_map if field_map is not None else os.getenv("SCREENER_FIELD_MAP_JSON")
        self.field_map = parse_field_map(raw_map)
        raw_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("SCREENER_TIMEOUT_SECONDS", "10")
        )
        self.timeout_seconds = max(1.0, float(raw_timeout))
        self.session = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.export_path or self.export_url)

    @staticmethod
    def _normalize_column(value: Any) -> str:
        return " ".join(str(value).strip().lower().replace("_", " ").split())

    def _load(self) -> tuple[pd.DataFrame, str]:
        if self.export_path:
            path = Path(self.export_path)
            if not path.exists():
                raise FileNotFoundError(f"Screener export not found: {path}")
            frame = pd.read_csv(path)
            as_of = datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat()
            return frame, as_of

        if self.export_url:
            response = self.session.get(
                self.export_url,
                headers={"Accept": "text/csv,*/*;q=0.8"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            frame = pd.read_csv(StringIO(response.text))
            as_of = response.headers.get("Last-Modified") or datetime.now(timezone.utc).isoformat()
            return frame, str(as_of)

        raise RuntimeError("Screener CSV export is not configured")

    def _symbol_column(self, frame: pd.DataFrame) -> str:
        if self.symbol_column:
            if self.symbol_column in frame.columns:
                return self.symbol_column
            normalized = {
                self._normalize_column(column): str(column)
                for column in frame.columns
            }
            match = normalized.get(self._normalize_column(self.symbol_column))
            if match:
                return match
            raise ValueError(
                f"Configured Screener symbol column not found: {self.symbol_column}"
            )

        normalized = {
            self._normalize_column(column): str(column)
            for column in frame.columns
        }
        for alias in self.SYMBOL_ALIASES:
            match = normalized.get(self._normalize_column(alias))
            if match:
                return match
        raise ValueError(
            "Screener export must include an NSE/symbol column or SCREENER_SYMBOL_COLUMN"
        )

    @staticmethod
    def _normalize_symbol(value: Any) -> str:
        symbol = str(value or "").strip().upper()
        if symbol.startswith("NSE:"):
            symbol = symbol[4:]
        if symbol.endswith(".NS"):
            symbol = symbol[:-3]
        return symbol

    def get(self, symbol: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        symbol = self._normalize_symbol(symbol)
        if not symbol:
            raise ValueError("Symbol is required for Screener fundamentals")
        if not self.configured:
            return None

        frame, as_of = self._load()
        if frame.empty:
            return None
        symbol_column = self._symbol_column(frame)
        symbols = frame[symbol_column].map(self._normalize_symbol)
        matches = frame.loc[symbols == symbol]
        if matches.empty:
            return None

        row = matches.iloc[0].to_dict()
        values = extract_fields(row, self.field_map)
        return build_snapshot(
            provider=self.NAME,
            symbol=symbol,
            values=values,
            as_of=as_of,
            extra_meta={
                "source": "screener_premium_csv_export",
                "export_path_configured": bool(self.export_path),
                "export_url_configured": bool(self.export_url),
            },
        )

    def get_fundamentals(self, symbol: str) -> dict[str, Any] | None:
        return self.get(symbol)

    def health(self) -> dict[str, Any]:
        return {
            "status": "configured" if self.configured else "not_configured",
            "provider": self.NAME,
            "network_probe": False,
            "mode": (
                "local_csv"
                if self.export_path
                else "remote_csv"
                if self.export_url
                else "unconfigured"
            ),
        }


__all__ = ["ScreenerProvider"]
