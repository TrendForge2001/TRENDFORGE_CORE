"""Yahoo-derived fundamental enrichment for the canonical scanner.

The provider deliberately exposes only fields that can be sourced or derived
without pretending that Yahoo's generic insider data is equivalent to Indian
promoter/pledge disclosures. Promoter holding and pledged shares therefore
remain missing until an authoritative India-specific provider is configured.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import time
from typing import Any, Callable, Iterable

import pandas as pd


class YahooFundamentalProvider:
    """Build a strict, provenance-rich fundamental snapshot from Yahoo data."""

    NAME = "YahooFundamentalProvider"
    STALE_AFTER_DAYS = 550
    CACHE_TTL_SECONDS = 24 * 60 * 60
    PARTIAL_CACHE_TTL_SECONDS = 5 * 60

    def __init__(
        self,
        provider: Any | None = None,
        *,
        stale_after_days: int | None = None,
        cache_ttl_seconds: int | None = None,
        partial_cache_ttl_seconds: int | None = None,
    ) -> None:
        self.provider = provider
        self.stale_after_days = max(1, int(stale_after_days or self.STALE_AFTER_DAYS))
        self.cache_ttl_seconds = max(1, int(cache_ttl_seconds or self.CACHE_TTL_SECONDS))
        self.partial_cache_ttl_seconds = max(
            1,
            int(partial_cache_ttl_seconds or self.PARTIAL_CACHE_TTL_SECONDS),
        )
        self._cache: dict[str, tuple[dict[str, Any], float, int]] = {}
        self._last_source_errors: dict[str, str] = {}

    def _provider(self):
        if self.provider is None:
            from providers.yfinance_provider import yfinance_provider
            self.provider = yfinance_provider
        return self.provider

    @staticmethod
    def _finite(value: Any) -> float | None:
        try:
            value = float(value)
            return value if math.isfinite(value) else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _percent_ratio(cls, value: Any) -> float | None:
        value = cls._finite(value)
        return None if value is None else value * 100.0

    @classmethod
    def _yahoo_debt_equity(cls, value: Any) -> float | None:
        """Yahoo's debtToEquity field is percentage-like (e.g. 45 == 0.45x)."""
        value = cls._finite(value)
        return None if value is None else max(0.0, value / 100.0)

    @staticmethod
    def _normalise_label(value: Any) -> str:
        return " ".join(str(value).strip().lower().replace("_", " ").split())

    @classmethod
    def _row(cls, frame: Any, labels: Iterable[str]) -> pd.Series | None:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return None
        wanted = {cls._normalise_label(label) for label in labels}
        for index in frame.index:
            if cls._normalise_label(index) in wanted:
                row = frame.loc[index]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                return row if isinstance(row, pd.Series) else None
        return None

    @classmethod
    def _values(cls, frame: Any, labels: Iterable[str]) -> list[float]:
        row = cls._row(frame, labels)
        if row is None:
            return []
        values: list[float] = []
        for raw in row.tolist():
            value = cls._finite(raw)
            if value is not None:
                values.append(value)
        return values

    @classmethod
    def _latest(cls, frame: Any, labels: Iterable[str]) -> float | None:
        values = cls._values(frame, labels)
        return values[0] if values else None

    @classmethod
    def _growth(cls, frame: Any, labels: Iterable[str]) -> float | None:
        values = cls._values(frame, labels)
        if len(values) < 2 or values[1] == 0:
            return None
        return ((values[0] - values[1]) / abs(values[1])) * 100.0

    @classmethod
    def _latest_date(cls, *frames: Any) -> datetime | None:
        dates: list[datetime] = []
        for frame in frames:
            if not isinstance(frame, pd.DataFrame):
                continue
            for column in frame.columns:
                try:
                    timestamp = pd.Timestamp(column)
                    if pd.isna(timestamp):
                        continue
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.tz_localize("UTC")
                    else:
                        timestamp = timestamp.tz_convert("UTC")
                    dates.append(timestamp.to_pydatetime())
                except Exception:
                    continue
        return max(dates) if dates else None

    @staticmethod
    def _info_date(info: dict[str, Any]) -> datetime | None:
        raw = info.get("lastFiscalYearEnd")
        if raw is None:
            return None
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    @classmethod
    def _derived_roce(cls, financials: Any, balance_sheet: Any) -> float | None:
        ebit = cls._latest(financials, ("EBIT", "Operating Income"))
        assets = cls._latest(balance_sheet, ("Total Assets",))
        current_liabilities = cls._latest(
            balance_sheet,
            ("Current Liabilities", "Total Current Liabilities"),
        )
        if ebit is None or assets is None or current_liabilities is None:
            return None
        capital_employed = assets - current_liabilities
        if capital_employed <= 0:
            return None
        return ebit / capital_employed * 100.0

    @classmethod
    def _derived_roe(cls, financials: Any, balance_sheet: Any) -> float | None:
        net_income = cls._latest(
            financials,
            ("Net Income", "Net Income Common Stockholders"),
        )
        equity = cls._latest(
            balance_sheet,
            ("Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"),
        )
        if net_income is None or equity is None or equity <= 0:
            return None
        return net_income / equity * 100.0

    @classmethod
    def _derived_debt_equity(cls, balance_sheet: Any) -> float | None:
        debt = cls._latest(
            balance_sheet,
            ("Total Debt", "Long Term Debt And Capital Lease Obligation"),
        )
        equity = cls._latest(
            balance_sheet,
            ("Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"),
        )
        if debt is None or equity is None or equity <= 0:
            return None
        return max(0.0, debt / equity)

    @staticmethod
    def _is_rate_limited(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(token in text for token in ("too many requests", "rate limit", "429"))

    @classmethod
    def _safe_source(
        cls,
        name: str,
        loader: Callable[[], Any],
        errors: dict[str, str],
        default: Any,
    ) -> Any:
        try:
            value = loader()
            return default if value is None else value
        except Exception as exc:
            prefix = "rate_limited" if cls._is_rate_limited(exc) else "error"
            errors[name] = f"{prefix}:{exc}"
            return default

    def _cached(self, symbol: str) -> dict[str, Any] | None:
        item = self._cache.get(symbol)
        if item is None:
            return None
        value, cached_at, ttl = item
        if time.time() - cached_at >= ttl:
            self._cache.pop(symbol, None)
            return None
        return deepcopy(value)

    def _store(
        self,
        symbol: str,
        value: dict[str, Any],
        *,
        partial: bool = False,
    ) -> dict[str, Any]:
        ttl = self.partial_cache_ttl_seconds if partial else self.cache_ttl_seconds
        self._cache[symbol] = (deepcopy(value), time.time(), ttl)
        return deepcopy(value)

    @staticmethod
    def _summary_roce(info: dict[str, Any]) -> float | None:
        value = YahooFundamentalProvider._finite(info.get("returnOnCapitalEmployed"))
        if value is not None and abs(value) <= 5:
            value *= 100.0
        return value

    @classmethod
    def _summary_fields(cls, info: dict[str, Any]) -> dict[str, float | None]:
        return {
            "roce": cls._summary_roce(info),
            "roe": cls._percent_ratio(info.get("returnOnEquity")),
            "sales_growth": cls._percent_ratio(info.get("revenueGrowth")),
            "profit_growth": cls._percent_ratio(info.get("earningsGrowth")),
            "eps_growth": cls._percent_ratio(info.get("earningsQuarterlyGrowth")),
            "debt_equity": cls._yahoo_debt_equity(info.get("debtToEquity")),
        }

    @classmethod
    def _statement_fields(
        cls,
        financials: Any,
        balance_sheet: Any,
    ) -> dict[str, float | None]:
        return {
            "roce": cls._derived_roce(financials, balance_sheet),
            "roe": cls._derived_roe(financials, balance_sheet),
            "sales_growth": cls._growth(
                financials,
                ("Total Revenue", "Operating Revenue"),
            ),
            "profit_growth": cls._growth(
                financials,
                ("Net Income", "Net Income Common Stockholders"),
            ),
            "eps_growth": cls._growth(
                financials,
                ("Diluted EPS", "Basic EPS"),
            ),
            "debt_equity": cls._derived_debt_equity(balance_sheet),
        }

    def get(self, symbol: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        symbol = str(symbol or "").strip().upper()
        if not symbol:
            raise ValueError("Symbol is required for fundamental enrichment")

        cached = self._cached(symbol)
        if cached is not None:
            return cached

        provider = self._provider()
        source_errors: dict[str, str] = {}

        # Prefer financial statements because Yahoo's heavy .info endpoint is
        # commonly throttled. They are sufficient to derive all six public
        # metrics when the statements contain the expected rows.
        financials = self._safe_source(
            "financials",
            lambda: provider.financials(symbol),
            source_errors,
            pd.DataFrame(),
        )
        balance_sheet = self._safe_source(
            "balance_sheet",
            lambda: provider.balance_sheet(symbol),
            source_errors,
            pd.DataFrame(),
        )
        fields = self._statement_fields(financials, balance_sheet)

        statement_as_of = self._latest_date(financials, balance_sheet)
        needs_info = any(value is None for value in fields.values()) or statement_as_of is None

        info: dict[str, Any] = {}
        if needs_info:
            loaded = self._safe_source(
                "company_info",
                lambda: provider.company_info(symbol),
                source_errors,
                {},
            )
            info = loaded if isinstance(loaded, dict) else {}
            summary = self._summary_fields(info)
            for name, value in summary.items():
                if fields.get(name) is None and value is not None:
                    fields[name] = value

        fields["promoter_holding"] = None
        fields["pledged"] = None

        as_of = max(
            [date for date in (statement_as_of, self._info_date(info)) if date is not None],
            default=None,
        )
        now = datetime.now(timezone.utc)
        age_days = (now - as_of).days if as_of is not None else None
        stale = as_of is None or age_days is None or age_days > self.stale_after_days

        missing = [name for name, value in fields.items() if self._finite(value) is None]
        warnings: list[str] = []
        for source, detail in source_errors.items():
            if detail.startswith("rate_limited:"):
                warnings.append(f"yahoo_rate_limited:{source}")
            else:
                warnings.append(f"yahoo_source_error:{source}")
        if stale:
            warnings.append("fundamental_snapshot_stale_or_undated")
        if "promoter_holding" in missing:
            warnings.append("promoter_holding_requires_authoritative_india_source")
        if "pledged" in missing:
            warnings.append("pledged_shares_require_authoritative_india_source")

        data = {
            name: float(value)
            for name, value in fields.items()
            if self._finite(value) is not None
        }
        data["_meta"] = {
            "provider": self.NAME,
            "symbol": symbol,
            "as_of": as_of.isoformat() if as_of is not None else None,
            "age_days": age_days,
            "stale": stale,
            "missing": missing,
            "warnings": warnings,
            "source_errors": dict(source_errors),
            "statement_first": True,
        }
        self._last_source_errors = dict(source_errors)
        return self._store(symbol, data, partial=bool(source_errors))

    def get_fundamentals(self, symbol: str) -> dict[str, Any]:
        return self.get(symbol)

    def health(self) -> dict[str, Any]:
        return {
            "status": "configured",
            "provider": self.NAME,
            "stale_after_days": self.stale_after_days,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "partial_cache_ttl_seconds": self.partial_cache_ttl_seconds,
            "cache_size": len(self._cache),
            "network_probe": False,
            "statement_first": True,
            "last_source_errors": dict(self._last_source_errors),
            "authoritative_promoter_data": False,
            "authoritative_pledge_data": False,
        }


__all__ = ["YahooFundamentalProvider"]
