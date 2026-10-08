"""Canonical enrichment adapters for non-fundamental scanner inputs."""

from __future__ import annotations

import math
import time
from typing import Any, Mapping

import pandas as pd


class CorporateActionEnrichmentProvider:
    """Expose the existing corporate-action domain provider to StockEnricher."""

    def __init__(self, provider: Any, cache_ttl: int = 3600) -> None:
        self.provider = provider
        self.cache_ttl = max(0, int(cache_ttl))
        self._cache: dict[str, tuple[list[dict[str, Any]], float]] = {}

    @staticmethod
    def _contains_symbol(item: Mapping[str, Any], symbol: str) -> bool:
        symbol = symbol.upper()
        for key in (
            "symbol", "symbols", "ticker", "security", "companyName",
            "company", "securityName",
        ):
            if symbol in str(item.get(key) or "").upper():
                return True
        return symbol in str(item).upper()

    def get(self, symbol: str, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        symbol = str(symbol or "").strip().upper()
        cached = self._cache.get(symbol)
        if cached is not None and time.time() - cached[1] <= self.cache_ttl:
            return list(cached[0])

        raw = self.provider.corporate_actions() or []
        actions: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            if symbol and not self._contains_symbol(item, symbol):
                continue
            subject = str(item.get("subject") or "").strip()
            purpose = str(item.get("purpose") or "").strip()
            title = " - ".join(part for part in (subject, purpose) if part)
            actions.append(
                {
                    "symbol": symbol,
                    "title": title,
                    "type": item.get("type") or item.get("event_type") or item.get("category"),
                    "date": (
                        item.get("date")
                        or item.get("event_date")
                        or item.get("announcement_date")
                        or item.get("exDate")
                    ),
                    "ex_date": item.get("ex_date") or item.get("exDate"),
                    "record_date": item.get("record_date") or item.get("recordDate"),
                    "raw": dict(item),
                }
            )

        self._cache[symbol] = (actions, time.time())
        return list(actions)

    def health(self) -> dict[str, Any]:
        return {
            "status": "configured",
            "provider": self.__class__.__name__,
            "source": type(self.provider).__name__,
            "network_probe": False,
        }


class YahooInstitutionalEnrichmentProvider:
    """Best-effort holder enrichment without inventing FII/DII classifications."""

    def __init__(self, yahoo: Any | None = None) -> None:
        self.yahoo = yahoo

    def _provider(self):
        if self.yahoo is None:
            from providers.yfinance_provider import yfinance_provider

            self.yahoo = yfinance_provider
        return self.yahoo

    @staticmethod
    def _rows(frame: Any, category: str) -> list[dict[str, Any]]:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return []

        rows: list[dict[str, Any]] = []
        normalized = frame.reset_index(drop=False)
        for raw in normalized.to_dict(orient="records"):
            name = (
                raw.get("Holder")
                or raw.get("holder")
                or raw.get("Name")
                or raw.get("name")
                or raw.get("index")
                or ""
            )
            holding = (
                raw.get("% Out")
                if raw.get("% Out") is not None
                else raw.get("pctHeld", raw.get("holding"))
            )
            value = raw.get("Value", raw.get("value"))
            row: dict[str, Any] = {
                "name": str(name).strip(),
                "category": category,
            }
            if holding is not None:
                row["holding"] = holding
            if value is not None:
                row["value"] = value
            date_value = (
                raw.get("Date Reported")
                or raw.get("dateReported")
                or raw.get("date")
            )
            if date_value is not None:
                row["date"] = str(date_value)
            rows.append(row)
        return rows

    def get(self, symbol: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        provider = self._provider()
        institutional = self._rows(provider.institutional_holders(symbol), "INSTITUTIONAL")
        mutual_funds = self._rows(provider.mutualfund_holders(symbol), "MUTUAL FUND")
        rows = institutional + mutual_funds
        if not rows:
            return None
        return {
            "institutional_holders": rows,
            "shareholders": rows,
            "_meta": {
                "provider": self.__class__.__name__,
                "coverage": {
                    "institutional_holders": len(institutional),
                    "mutual_fund_holders": len(mutual_funds),
                },
                "classification_note": (
                    "Yahoo holder tables are not reclassified as FII/DII "
                    "without source evidence."
                ),
            },
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "configured",
            "provider": self.__class__.__name__,
            "network_probe": False,
            "classification": "conservative",
        }


class YahooSectorEnrichmentProvider:
    """Resolve a stock sector and score a representative NSE sector proxy."""

    DEFAULT_BENCHMARK = "^NSEI"
    PROXIES = (
        (("pharma", "drug", "biotech", "healthcare"), "^CNXPHARMA"),
        (("software", "information technology", "technology", "it services"), "^CNXIT"),
        (("bank",), "^NSEBANK"),
        (("finance", "financial", "capital market", "exchange"), "^CNXFINANCE"),
        (("automobile", "auto", "vehicle"), "^CNXAUTO"),
        (("metal", "steel", "mining"), "^CNXMETAL"),
        (("oil", "gas", "energy", "power"), "^CNXENERGY"),
        (("fmcg", "consumer defensive", "food", "beverage", "household"), "^CNXFMCG"),
        (("real estate", "realty"), "^CNXREALTY"),
        (("media", "entertainment"), "^CNXMEDIA"),
    )

    def __init__(self, yahoo: Any | None = None) -> None:
        self.yahoo = yahoo

    def _provider(self):
        if self.yahoo is None:
            from providers.yfinance_provider import yfinance_provider

            self.yahoo = yfinance_provider
        return self.yahoo

    @classmethod
    def _proxy(cls, sector: str, industry: str) -> str | None:
        text = f"{sector} {industry}".lower()
        for keywords, proxy in cls.PROXIES:
            if any(keyword in text for keyword in keywords):
                return proxy
        return None

    @staticmethod
    def _close(frame: pd.DataFrame) -> pd.Series | None:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return None
        for key in ("Close", "close"):
            if key in frame.columns:
                series = pd.to_numeric(frame[key], errors="coerce").dropna()
                return series if not series.empty else None
        return None

    @staticmethod
    def _pct_change(series: pd.Series | None, periods: int) -> float | None:
        if series is None or len(series) <= periods:
            return None
        current = float(series.iloc[-1])
        previous = float(series.iloc[-(periods + 1)])
        if not math.isfinite(current) or not math.isfinite(previous) or previous == 0:
            return None
        return round((current / previous - 1.0) * 100.0, 4)

    @staticmethod
    def _volume_ratio(frame: pd.DataFrame) -> float | None:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return None
        column = "Volume" if "Volume" in frame.columns else "volume" if "volume" in frame.columns else None
        if column is None:
            return None
        volume = pd.to_numeric(frame[column], errors="coerce").dropna()
        if len(volume) < 2:
            return None
        window = volume.tail(20)
        average = float(window.mean())
        latest = float(volume.iloc[-1])
        if average <= 0 or not math.isfinite(average) or not math.isfinite(latest):
            return None
        return round(latest / average, 4)

    def get(self, symbol: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        provider = self._provider()
        info = provider.company_info(symbol) or {}
        sector = str(info.get("sector") or "").strip()
        industry = str(info.get("industry") or "").strip()
        proxy = self._proxy(sector, industry)
        if not sector or proxy is None:
            return None

        sector_frame = provider.historical_data(
            proxy, period="6mo", interval="1d", auto_adjust=False
        )
        close = self._close(sector_frame)
        if close is None:
            return None

        benchmark_return = None
        try:
            benchmark_frame = provider.historical_data(
                self.DEFAULT_BENCHMARK,
                period="6mo",
                interval="1d",
                auto_adjust=False,
            )
            benchmark_return = self._pct_change(self._close(benchmark_frame), 21)
        except Exception:
            benchmark_return = None

        return {
            "sector": sector,
            "industry": industry,
            "proxy_symbol": proxy,
            "change_1d": self._pct_change(close, 1),
            "change_1w": self._pct_change(close, 5),
            "change_1m": self._pct_change(close, 21),
            "change_3m": self._pct_change(close, 63),
            "volume_ratio": self._volume_ratio(sector_frame),
            "market_return": benchmark_return,
            "_meta": {
                "provider": self.__class__.__name__,
                "benchmark": self.DEFAULT_BENCHMARK,
            },
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "configured",
            "provider": self.__class__.__name__,
            "network_probe": False,
            "benchmark": self.DEFAULT_BENCHMARK,
            "proxy_count": len(self.PROXIES),
        }


__all__ = [
    "CorporateActionEnrichmentProvider",
    "YahooInstitutionalEnrichmentProvider",
    "YahooSectorEnrichmentProvider",
]
