"""Canonical enrichment adapters for non-fundamental scanner inputs."""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Mapping

import pandas as pd


class _RuntimeState:
    """Small runtime-state helper without adding health-check network traffic."""

    def _init_runtime_state(
        self,
        *,
        failure_cooldown_seconds: int = 0,
    ) -> None:
        self._runtime_lock = threading.Lock()
        self._last_success_at: float | None = None
        self._last_error: str | None = None
        self._cooldown_until = 0.0
        self._failure_cooldown_seconds = max(
            0,
            int(failure_cooldown_seconds),
        )

    @staticmethod
    def _is_rate_limit_error(exc: Exception | str) -> bool:
        text = str(exc).lower()
        return (
            "too many requests" in text
            or "rate limit" in text
            or "rate_limited" in text
            or "http 429" in text
            or "status code 429" in text
        )

    def _cooldown_remaining(self) -> int:
        return max(
            0,
            int(round(self._cooldown_until - time.time())),
        )

    def _guard_cooldown(self, label: str) -> None:
        remaining = self._cooldown_remaining()
        if remaining > 0:
            raise RuntimeError(
                f"{label} cooldown active; retry in {remaining}s"
            )

    def _mark_success(self) -> None:
        with self._runtime_lock:
            self._last_success_at = time.time()
            self._last_error = None
            self._cooldown_until = 0.0

    def _mark_failure(
        self,
        exc: Exception | str,
        *,
        rate_limit_cooldown_seconds: int = 0,
        cooldown_on_any_failure: bool = False,
    ) -> None:
        text = str(exc)
        with self._runtime_lock:
            self._last_error = text
            cooldown = 0
            if self._is_rate_limit_error(text):
                cooldown = max(
                    cooldown,
                    int(rate_limit_cooldown_seconds),
                )
            if cooldown_on_any_failure:
                cooldown = max(
                    cooldown,
                    self._failure_cooldown_seconds,
                )
            if cooldown > 0:
                self._cooldown_until = max(
                    self._cooldown_until,
                    time.time() + cooldown,
                )

    def _runtime_health(self) -> dict[str, Any]:
        remaining = self._cooldown_remaining()
        if remaining > 0:
            status = "degraded"
            runtime_status = (
                "rate_limited"
                if self._last_error
                and self._is_rate_limit_error(self._last_error)
                else "cooldown"
            )
        elif self._last_success_at is not None:
            status = "runtime_verified"
            runtime_status = "runtime_verified"
        elif self._last_error:
            status = "degraded"
            runtime_status = "failed"
        else:
            status = "configured"
            runtime_status = "not_probed"

        return {
            "status": status,
            "runtime_status": runtime_status,
            "network_probe": False,
            "last_success_at_epoch": self._last_success_at,
            "last_error": self._last_error,
            "retry_after_seconds": remaining,
        }


class CorporateActionEnrichmentProvider(_RuntimeState):
    """Expose NSE corporate actions with scoped retrieval and failure cooldown."""

    def __init__(
        self,
        provider: Any,
        cache_ttl: int = 3600,
        failure_cooldown_seconds: int = 120,
    ) -> None:
        self.provider = provider
        self.cache_ttl = max(0, int(cache_ttl))
        self._cache: dict[
            str,
            tuple[list[dict[str, Any]], float],
        ] = {}
        self._init_runtime_state(
            failure_cooldown_seconds=failure_cooldown_seconds
        )

    @staticmethod
    def _rows(value: Any) -> list[Mapping[str, Any]]:
        if isinstance(value, list):
            return [
                item for item in value
                if isinstance(item, Mapping)
            ]
        if isinstance(value, Mapping):
            for key in (
                "data",
                "rows",
                "results",
                "items",
                "actions",
                "corporate_actions",
            ):
                nested = value.get(key)
                if isinstance(nested, list):
                    return [
                        item for item in nested
                        if isinstance(item, Mapping)
                    ]
            if any(
                key in value
                for key in (
                    "symbol",
                    "Symbol",
                    "subject",
                    "purpose",
                    "exDate",
                    "recDate",
                )
            ):
                return [value]
        return []

    @staticmethod
    def _item_symbol(item: Mapping[str, Any]) -> str:
        return str(
            item.get("symbol")
            or item.get("Symbol")
            or item.get("SYMBOL")
            or item.get("ticker")
            or item.get("security")
            or ""
        ).strip().upper()

    @classmethod
    def _contains_symbol(
        cls,
        item: Mapping[str, Any],
        symbol: str,
    ) -> bool:
        item_symbol = cls._item_symbol(item)
        if item_symbol:
            return item_symbol == symbol

        for key in (
            "symbols",
            "companyName",
            "company",
            "securityName",
            "comp",
        ):
            if symbol in str(item.get(key) or "").upper():
                return True
        return False

    def _fetch(self, symbol: str) -> Any:
        method = self.provider.corporate_actions
        try:
            return method(symbol=symbol, days=120)
        except TypeError:
            try:
                return method(symbol=symbol)
            except TypeError:
                return method()

    def get(
        self,
        symbol: str,
        payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        symbol = str(symbol or "").strip().upper()
        cached = self._cache.get(symbol)
        if (
            cached is not None
            and time.time() - cached[1] <= self.cache_ttl
        ):
            return list(cached[0])

        self._guard_cooldown("Corporate-actions upstream")

        try:
            raw = self._fetch(symbol) or []
            rows = self._rows(raw)
        except Exception as exc:
            self._mark_failure(
                exc,
                cooldown_on_any_failure=True,
            )
            raise

        actions: list[dict[str, Any]] = []
        for item in rows:
            if symbol and not self._contains_symbol(item, symbol):
                continue

            subject = str(
                item.get("subject")
                or item.get("purpose")
                or ""
            ).strip()
            purpose = str(
                item.get("purpose")
                or item.get("remarks")
                or ""
            ).strip()
            title = " - ".join(
                dict.fromkeys(
                    part for part in (subject, purpose) if part
                )
            )

            actions.append(
                {
                    "symbol": symbol,
                    "title": title,
                    "type": (
                        item.get("type")
                        or item.get("event_type")
                        or item.get("category")
                        or item.get("subject")
                    ),
                    "date": (
                        item.get("date")
                        or item.get("event_date")
                        or item.get("announcement_date")
                        or item.get("exDate")
                        or item.get("ex_date")
                    ),
                    "ex_date": (
                        item.get("ex_date")
                        or item.get("exDate")
                    ),
                    "record_date": (
                        item.get("record_date")
                        or item.get("recordDate")
                        or item.get("recDate")
                    ),
                    "raw": dict(item),
                }
            )

        self._cache[symbol] = (actions, time.time())
        self._mark_success()
        return list(actions)

    def health(self) -> dict[str, Any]:
        return {
            **self._runtime_health(),
            "provider": self.__class__.__name__,
            "source": type(self.provider).__name__,
            "cache_ttl_seconds": self.cache_ttl,
            "cached_symbols": len(self._cache),
        }


class YahooInstitutionalEnrichmentProvider(_RuntimeState):
    """Institutional enrichment with Yahoo holders and NSE large-deal fallback."""

    def __init__(
        self,
        yahoo: Any | None = None,
        nse: Any | None = None,
        *,
        cache_ttl: int = 21600,
        deal_cache_ttl: int = 900,
        yahoo_rate_limit_cooldown: int = 900,
    ) -> None:
        self.yahoo = yahoo
        self.nse = nse
        self.cache_ttl = max(0, int(cache_ttl))
        self.deal_cache_ttl = max(0, int(deal_cache_ttl))
        self.yahoo_rate_limit_cooldown = max(
            0,
            int(yahoo_rate_limit_cooldown),
        )
        self._use_default_nse = yahoo is None and nse is None
        self._cache: dict[
            str,
            tuple[dict[str, Any], float],
        ] = {}
        self._deal_cache: tuple[
            list[dict[str, Any]],
            float,
        ] | None = None
        self._yahoo_cooldown_until = 0.0
        self._init_runtime_state()

    def _provider(self):
        if self.yahoo is None:
            from providers.yfinance_provider import yfinance_provider

            self.yahoo = yfinance_provider
        return self.yahoo

    def _nse_provider(self):
        if self.nse is None and self._use_default_nse:
            from providers.nse_provider import nse_provider

            self.nse = nse_provider
        return self.nse

    def _yahoo_cooldown_remaining(self) -> int:
        return max(
            0,
            int(round(self._yahoo_cooldown_until - time.time())),
        )

    def _mark_yahoo_failure(self, exc: Exception | str) -> None:
        if self._is_rate_limit_error(exc):
            self._yahoo_cooldown_until = max(
                self._yahoo_cooldown_until,
                time.time() + self.yahoo_rate_limit_cooldown,
            )

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

    @staticmethod
    def _payload_rows(value: Any) -> list[Mapping[str, Any]]:
        if isinstance(value, list):
            return [
                row for row in value
                if isinstance(row, Mapping)
            ]
        if isinstance(value, Mapping):
            for key in (
                "data",
                "rows",
                "results",
                "items",
                "deals",
            ):
                nested = value.get(key)
                if isinstance(nested, list):
                    return [
                        row for row in nested
                        if isinstance(row, Mapping)
                    ]
        return []

    @staticmethod
    def _first(
        row: Mapping[str, Any],
        *keys: str,
    ) -> Any:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
        return None

    @classmethod
    def _normalize_deal(
        cls,
        row: Mapping[str, Any],
    ) -> dict[str, Any]:
        symbol = str(
            cls._first(
                row,
                "symbol",
                "Symbol",
                "SYMBOL",
                "tradingsymbol",
            )
            or ""
        ).strip().upper()

        side = str(
            cls._first(
                row,
                "buy_sell",
                "buySell",
                "BUY_SELL",
                "side",
                "transaction_type",
            )
            or ""
        ).strip().upper()
        if side == "B":
            side = "BUY"
        elif side == "S":
            side = "SELL"

        client = str(
            cls._first(
                row,
                "client_name",
                "clientName",
                "Client Name",
                "client",
            )
            or ""
        ).strip()

        quantity = cls._first(
            row,
            "quantity_traded",
            "quantityTraded",
            "Quantity Traded",
            "quantity",
            "qty",
        )
        price = cls._first(
            row,
            "trade_price",
            "tradePrice",
            "Trade Price / Wght. Avg. Price",
            "price",
        )

        value_crore = cls._first(
            row,
            "value_crore",
            "trade_value_cr",
            "transaction_value",
            "amount",
        )

        if value_crore in (None, ""):
            try:
                value_crore = (
                    float(quantity) * float(price) / 10_000_000
                )
            except (TypeError, ValueError):
                value_crore = None

        return {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "value_crore": value_crore,
            "buyer": client if side == "BUY" else "",
            "seller": client if side == "SELL" else "",
            "client_name": client,
            "date": cls._first(
                row,
                "date",
                "trade_date",
                "tradeDate",
                "Date",
            ),
            "raw": dict(row),
        }

    def _load_nse_deals(
        self,
    ) -> tuple[list[dict[str, Any]], bool, list[str]]:
        cached = self._deal_cache
        if (
            cached is not None
            and time.time() - cached[1] <= self.deal_cache_ttl
        ):
            return list(cached[0]), True, []

        provider = self._nse_provider()
        if provider is None:
            return [], False, []

        deals: list[dict[str, Any]] = []
        errors: list[str] = []
        success = False

        for name in ("bulk_deals", "block_deals"):
            method = getattr(provider, name, None)
            if not callable(method):
                continue

            try:
                payload = method(days=30)
                success = True
                for row in self._payload_rows(payload):
                    normalized = self._normalize_deal(row)
                    if normalized["symbol"]:
                        normalized["deal_type"] = (
                            "BULK"
                            if name == "bulk_deals"
                            else "BLOCK"
                        )
                        deals.append(normalized)
            except TypeError:
                try:
                    payload = method()
                    success = True
                    for row in self._payload_rows(payload):
                        normalized = self._normalize_deal(row)
                        if normalized["symbol"]:
                            normalized["deal_type"] = (
                                "BULK"
                                if name == "bulk_deals"
                                else "BLOCK"
                            )
                            deals.append(normalized)
                except Exception as exc:
                    errors.append(f"{name}:{exc}")
            except Exception as exc:
                errors.append(f"{name}:{exc}")

        if success:
            self._deal_cache = (deals, time.time())

        return deals, success, errors

    def get(
        self,
        symbol: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        symbol = str(symbol or "").strip().upper()
        cached = self._cache.get(symbol)
        if (
            cached is not None
            and time.time() - cached[1] <= self.cache_ttl
        ):
            return dict(cached[0])

        source_errors: list[str] = []
        institutional: list[dict[str, Any]] = []
        mutual_funds: list[dict[str, Any]] = []
        yahoo_success = False

        if self._yahoo_cooldown_remaining() <= 0:
            try:
                provider = self._provider()
                institutional = self._rows(
                    provider.institutional_holders(symbol),
                    "INSTITUTIONAL",
                )
                mutual_funds = self._rows(
                    provider.mutualfund_holders(symbol),
                    "MUTUAL FUND",
                )
                yahoo_success = True
            except Exception as exc:
                self._mark_yahoo_failure(exc)
                source_errors.append(f"yahoo:{exc}")
        else:
            source_errors.append(
                "yahoo:rate_limit_cooldown_active"
            )

        deals, nse_success, nse_errors = self._load_nse_deals()
        source_errors.extend(
            f"nse:{error}" for error in nse_errors
        )
        symbol_deals = [
            row for row in deals
            if row.get("symbol") == symbol
        ]

        if not yahoo_success and not nse_success:
            message = (
                "; ".join(source_errors)
                or "No institutional enrichment source is available"
            )
            self._mark_failure(message)
            raise RuntimeError(message)

        rows = institutional + mutual_funds
        result: dict[str, Any] = {
            "_meta": {
                "provider": self.__class__.__name__,
                "coverage": {
                    "institutional_holders": len(institutional),
                    "mutual_fund_holders": len(mutual_funds),
                    "large_deals": len(symbol_deals),
                },
                "yahoo_runtime_verified": yahoo_success,
                "nse_deals_runtime_verified": nse_success,
                "yahoo_retry_after_seconds":
                    self._yahoo_cooldown_remaining(),
                "source_errors": source_errors,
                "classification_note": (
                    "Yahoo holder tables are not reclassified as FII/DII "
                    "without source evidence."
                ),
            },
        }
        if rows:
            result["institutional_holders"] = rows
            result["shareholders"] = rows
        if symbol_deals:
            result["deals"] = symbol_deals
            result["bulk_deals"] = [
                row for row in symbol_deals
                if row.get("deal_type") == "BULK"
            ]
            result["block_deals"] = [
                row for row in symbol_deals
                if row.get("deal_type") == "BLOCK"
            ]

        self._cache[symbol] = (result, time.time())
        self._mark_success()
        return dict(result)

    def health(self) -> dict[str, Any]:
        return {
            **self._runtime_health(),
            "provider": self.__class__.__name__,
            "classification": "conservative",
            "cache_ttl_seconds": self.cache_ttl,
            "deal_cache_ttl_seconds": self.deal_cache_ttl,
            "cached_symbols": len(self._cache),
            "yahoo_retry_after_seconds":
                self._yahoo_cooldown_remaining(),
            "nse_fallback_enabled": (
                self._nse_provider() is not None
            ),
        }


class YahooSectorEnrichmentProvider(_RuntimeState):
    """Resolve sector from NSE first, then score a cached Yahoo sector proxy."""

    DEFAULT_BENCHMARK = "^NSEI"

    PROXIES = (
        (
            ("pharma", "drug", "biotech", "healthcare"),
            "^CNXPHARMA",
        ),
        (
            (
                "software",
                "information technology",
                "technology",
                "it services",
            ),
            "^CNXIT",
        ),
        (("bank",), "^NSEBANK"),
        (
            (
                "finance",
                "financial",
                "capital market",
                "exchange",
            ),
            "NIFTY_FIN_SERVICE.NS",
        ),
        (("automobile", "auto", "vehicle"), "^CNXAUTO"),
        (("metal", "steel", "mining"), "^CNXMETAL"),
        (
            ("oil", "gas", "energy", "power"),
            "^CNXENERGY",
        ),
        (
            (
                "industrial",
                "capital goods",
                "engineering",
                "infrastructure",
                "electrical equipment",
            ),
            "^CNXINFRA",
        ),
        (
            (
                "fmcg",
                "consumer defensive",
                "food",
                "beverage",
                "household",
            ),
            "^CNXFMCG",
        ),
        (("real estate", "realty"), "^CNXREALTY"),
        (("media", "entertainment"), "^CNXMEDIA"),
    )

    def __init__(
        self,
        yahoo: Any | None = None,
        nse: Any | None = None,
        *,
        cache_ttl: int = 21600,
        history_cache_ttl: int = 900,
        yahoo_rate_limit_cooldown: int = 900,
    ) -> None:
        self.yahoo = yahoo
        self.nse = nse
        self.cache_ttl = max(0, int(cache_ttl))
        self.history_cache_ttl = max(
            0,
            int(history_cache_ttl),
        )
        self.yahoo_rate_limit_cooldown = max(
            0,
            int(yahoo_rate_limit_cooldown),
        )
        self._use_default_nse = yahoo is None and nse is None
        self._cache: dict[
            str,
            tuple[dict[str, Any], float],
        ] = {}
        self._history_cache: dict[
            str,
            tuple[pd.DataFrame, float],
        ] = {}
        self._yahoo_cooldown_until = 0.0
        self._init_runtime_state()

    def _provider(self):
        if self.yahoo is None:
            from providers.yfinance_provider import yfinance_provider

            self.yahoo = yfinance_provider
        return self.yahoo

    def _nse_provider(self):
        if self.nse is None and self._use_default_nse:
            from providers.nse_provider import nse_provider

            self.nse = nse_provider
        return self.nse

    def _yahoo_cooldown_remaining(self) -> int:
        return max(
            0,
            int(round(self._yahoo_cooldown_until - time.time())),
        )

    def _mark_yahoo_failure(self, exc: Exception | str) -> None:
        if self._is_rate_limit_error(exc):
            self._yahoo_cooldown_until = max(
                self._yahoo_cooldown_until,
                time.time() + self.yahoo_rate_limit_cooldown,
            )

    @classmethod
    def _proxy(
        cls,
        sector: str,
        industry: str,
    ) -> str | None:
        text = f"{sector} {industry}".lower()
        for keywords, proxy in cls.PROXIES:
            if any(keyword in text for keyword in keywords):
                return proxy
        return None

    @staticmethod
    def _close(
        frame: pd.DataFrame,
    ) -> pd.Series | None:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return None
        for key in ("Close", "close"):
            if key in frame.columns:
                series = pd.to_numeric(
                    frame[key],
                    errors="coerce",
                ).dropna()
                return series if not series.empty else None
        return None

    @staticmethod
    def _pct_change(
        series: pd.Series | None,
        periods: int,
    ) -> float | None:
        if series is None or len(series) <= periods:
            return None
        current = float(series.iloc[-1])
        previous = float(series.iloc[-(periods + 1)])
        if (
            not math.isfinite(current)
            or not math.isfinite(previous)
            or previous == 0
        ):
            return None
        return round(
            (current / previous - 1.0) * 100.0,
            4,
        )

    @staticmethod
    def _volume_ratio(
        frame: pd.DataFrame,
    ) -> float | None:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return None
        column = (
            "Volume"
            if "Volume" in frame.columns
            else "volume"
            if "volume" in frame.columns
            else None
        )
        if column is None:
            return None
        volume = pd.to_numeric(
            frame[column],
            errors="coerce",
        ).dropna()
        if len(volume) < 2:
            return None
        window = volume.tail(20)
        average = float(window.mean())
        latest = float(volume.iloc[-1])
        if (
            average <= 0
            or not math.isfinite(average)
            or not math.isfinite(latest)
        ):
            return None
        return round(latest / average, 4)

    @staticmethod
    def _nse_sector_metadata(
        quote: Any,
    ) -> tuple[str, str]:
        if not isinstance(quote, Mapping):
            return "", ""

        industry_info = quote.get("industryInfo")
        if isinstance(industry_info, Mapping):
            sector = str(
                industry_info.get("sector")
                or industry_info.get("macro")
                or ""
            ).strip()
            industry = str(
                industry_info.get("industry")
                or industry_info.get("basicIndustry")
                or ""
            ).strip()
            return sector, industry

        metadata = quote.get("metadata")
        if isinstance(metadata, Mapping):
            sector = str(
                metadata.get("sector")
                or metadata.get("macro")
                or ""
            ).strip()
            industry = str(
                metadata.get("industry")
                or metadata.get("basicIndustry")
                or ""
            ).strip()
            if sector:
                return sector, industry

        return "", ""

    def _metadata(
        self,
        symbol: str,
    ) -> tuple[str, str, str, list[str]]:
        errors: list[str] = []

        nse = self._nse_provider()
        if nse is not None:
            try:
                sector, industry = self._nse_sector_metadata(
                    nse.equity_quote(symbol)
                )
                if sector:
                    return sector, industry, "NSE", errors
            except Exception as exc:
                errors.append(f"nse:{exc}")

        if self._yahoo_cooldown_remaining() > 0:
            errors.append("yahoo:rate_limit_cooldown_active")
            return "", "", "", errors

        try:
            info = self._provider().company_info(symbol) or {}
            sector = str(info.get("sector") or "").strip()
            industry = str(info.get("industry") or "").strip()
            if sector:
                return sector, industry, "Yahoo", errors
            errors.append("yahoo:sector_metadata_missing")
        except Exception as exc:
            self._mark_yahoo_failure(exc)
            errors.append(f"yahoo:{exc}")

        return "", "", "", errors

    def _history(
        self,
        symbol: str,
    ) -> pd.DataFrame:
        cached = self._history_cache.get(symbol)
        if (
            cached is not None
            and time.time() - cached[1] <= self.history_cache_ttl
        ):
            return cached[0]

        frame = self._provider().historical_data(
            symbol,
            period="6mo",
            interval="1d",
            auto_adjust=False,
        )
        if not isinstance(frame, pd.DataFrame):
            raise RuntimeError(
                f"Yahoo history returned invalid data for {symbol}"
            )

        self._history_cache[symbol] = (frame, time.time())
        return frame

    def get(
        self,
        symbol: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        symbol = str(symbol or "").strip().upper()
        cached = self._cache.get(symbol)
        if (
            cached is not None
            and time.time() - cached[1] <= self.cache_ttl
        ):
            return dict(cached[0])

        sector, industry, metadata_source, errors = (
            self._metadata(symbol)
        )
        if not sector:
            message = (
                "; ".join(errors)
                or "Sector metadata unavailable"
            )
            self._mark_failure(message)
            raise RuntimeError(message)

        proxy = self._proxy(sector, industry)
        if proxy is None:
            result = {
                "sector": sector,
                "industry": industry,
                "_meta": {
                    "provider": self.__class__.__name__,
                    "metadata_source": metadata_source,
                    "proxy_available": False,
                    "source_errors": errors,
                },
            }
            self._cache[symbol] = (result, time.time())
            self._mark_success()
            return dict(result)

        try:
            sector_frame = self._history(proxy)
            close = self._close(sector_frame)
            if close is None:
                raise RuntimeError(
                    f"Sector proxy history unavailable for {proxy}"
                )

            benchmark_frame = self._history(
                self.DEFAULT_BENCHMARK
            )
            benchmark_return = self._pct_change(
                self._close(benchmark_frame),
                21,
            )
        except Exception as exc:
            self._mark_yahoo_failure(exc)
            self._mark_failure(
                f"history:{exc}",
                rate_limit_cooldown_seconds=
                    self.yahoo_rate_limit_cooldown,
            )
            raise

        result = {
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
                "metadata_source": metadata_source,
                "benchmark": self.DEFAULT_BENCHMARK,
                "source_errors": errors,
            },
        }

        self._cache[symbol] = (result, time.time())
        self._mark_success()
        return dict(result)

    def health(self) -> dict[str, Any]:
        return {
            **self._runtime_health(),
            "provider": self.__class__.__name__,
            "benchmark": self.DEFAULT_BENCHMARK,
            "proxy_count": len(self.PROXIES),
            "cache_ttl_seconds": self.cache_ttl,
            "history_cache_ttl_seconds": self.history_cache_ttl,
            "cached_symbols": len(self._cache),
            "cached_histories": len(self._history_cache),
            "yahoo_retry_after_seconds":
                self._yahoo_cooldown_remaining(),
            "nse_metadata_fallback_enabled": (
                self._nse_provider() is not None
            ),
        }


__all__ = [
    "CorporateActionEnrichmentProvider",
    "YahooInstitutionalEnrichmentProvider",
    "YahooSectorEnrichmentProvider",
]
