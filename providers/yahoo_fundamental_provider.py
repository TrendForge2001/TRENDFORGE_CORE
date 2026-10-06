"""Yahoo-derived fundamental enrichment for the canonical scanner.

The provider deliberately exposes only fields that can be sourced or derived
without pretending that Yahoo's generic insider data is equivalent to Indian
promoter/pledge disclosures. Promoter holding and pledged shares therefore
remain missing until an authoritative India-specific provider is configured.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Iterable

import pandas as pd


class YahooFundamentalProvider:
    """Build a strict, provenance-rich fundamental snapshot from Yahoo data."""

    NAME = "YahooFundamentalProvider"
    STALE_AFTER_DAYS = 550

    def __init__(self, provider: Any | None = None, *, stale_after_days: int | None = None) -> None:
        self.provider = provider
        self.stale_after_days = max(1, int(stale_after_days or self.STALE_AFTER_DAYS))

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

    def get(self, symbol: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        symbol = str(symbol or "").strip().upper()
        if not symbol:
            raise ValueError("Symbol is required for fundamental enrichment")

        provider = self._provider()
        info = provider.company_info(symbol) or {}
        financials = provider.financials(symbol)
        balance_sheet = provider.balance_sheet(symbol)

        roe = self._percent_ratio(info.get("returnOnEquity"))
        if roe is None:
            roe = self._derived_roe(financials, balance_sheet)

        roce = self._finite(info.get("returnOnCapitalEmployed"))
        if roce is not None and abs(roce) <= 5:
            roce *= 100.0
        if roce is None:
            roce = self._derived_roce(financials, balance_sheet)

        sales_growth = self._percent_ratio(info.get("revenueGrowth"))
        if sales_growth is None:
            sales_growth = self._growth(financials, ("Total Revenue", "Operating Revenue"))

        profit_growth = self._percent_ratio(info.get("earningsGrowth"))
        if profit_growth is None:
            profit_growth = self._growth(
                financials,
                ("Net Income", "Net Income Common Stockholders"),
            )

        eps_growth = self._percent_ratio(info.get("earningsQuarterlyGrowth"))
        if eps_growth is None:
            eps_growth = self._growth(financials, ("Diluted EPS", "Basic EPS"))

        debt_equity = self._yahoo_debt_equity(info.get("debtToEquity"))
        if debt_equity is None:
            debt_equity = self._derived_debt_equity(balance_sheet)

        fields = {
            "roce": roce,
            "roe": roe,
            "sales_growth": sales_growth,
            "profit_growth": profit_growth,
            "eps_growth": eps_growth,
            "debt_equity": debt_equity,
            # Intentionally not inferred from Yahoo insider ownership.
            "promoter_holding": None,
            "pledged": None,
        }

        as_of = max(
            [date for date in (
                self._info_date(info),
                self._latest_date(financials, balance_sheet),
            ) if date is not None],
            default=None,
        )
        now = datetime.now(timezone.utc)
        age_days = (now - as_of).days if as_of is not None else None
        stale = as_of is None or age_days is None or age_days > self.stale_after_days

        missing = [name for name, value in fields.items() if self._finite(value) is None]
        warnings: list[str] = []
        if stale:
            warnings.append("fundamental_snapshot_stale_or_undated")
        if "promoter_holding" in missing:
            warnings.append("promoter_holding_requires_authoritative_india_source")
        if "pledged" in missing:
            warnings.append("pledged_shares_require_authoritative_india_source")

        data = {name: float(value) for name, value in fields.items() if self._finite(value) is not None}
        data["_meta"] = {
            "provider": self.NAME,
            "symbol": symbol,
            "as_of": as_of.isoformat() if as_of is not None else None,
            "age_days": age_days,
            "stale": stale,
            "missing": missing,
            "warnings": warnings,
        }
        return data

    def get_fundamentals(self, symbol: str) -> dict[str, Any]:
        return self.get(symbol)

    def health(self) -> dict[str, Any]:
        return {
            "status": "configured",
            "provider": self.NAME,
            "stale_after_days": self.stale_after_days,
            "network_probe": False,
            "authoritative_promoter_data": False,
            "authoritative_pledge_data": False,
        }


__all__ = ["YahooFundamentalProvider"]
