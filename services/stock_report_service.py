"""Read-only stock report evidence; approved strategy rules own trade levels."""

import logging
import math
import re
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd

from providers.company_report_provider import CompanyReportProvider
from scanner.strategy_horizons import horizon_strategy
from scanner.strategy_registry import REGISTRY_VERSION, get_strategy
from services.conditional_stock_plan import conditional_plan
from services.scanner_data_health import provider_detail
from services.stock_report_rules import readable_rules

LOG = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Kolkata")
DEFAULTS = {
    "short_term": "tf_swing_ema20_50_rsi_volume",
    "long_term": "tf_long_ema100_200",
}


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def safe_url(value):
    value = str(value or "")
    parsed = urlparse(value)
    return (
        value
        if parsed.scheme in {"http", "https"}
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        else None
    )


def news_rows(items, now):
    result = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        payload = item.get("content") if isinstance(item.get("content"), dict) else item
        title = str(payload.get("title") or payload.get("subject") or "").strip()[:300]
        canonical = payload.get("canonicalUrl") or {}
        link = safe_url(
            payload.get("link")
            or payload.get("url")
            or (canonical.get("url") if isinstance(canonical, dict) else None)
        )
        raw = (
            payload.get("providerPublishTime")
            or payload.get("pubDate")
            or payload.get("published")
            or payload.get("date")
        )
        date_only = (
            isinstance(raw, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) is not None
        )
        try:
            stamp = (
                pd.to_datetime(raw, unit="s", utc=True)
                if isinstance(raw, (int, float))
                else pd.Timestamp(raw)
            )
            if pd.isna(stamp) or (stamp.tzinfo is None and not date_only):
                continue
            if date_only:
                stamp = stamp.tz_localize(TZ)
            if stamp > now or stamp < pd.Timestamp(now) - pd.Timedelta(days=30):
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        provider = payload.get("provider") or {}
        source = (
            payload.get("publisher")
            or payload.get("source")
            or (provider.get("displayName") if isinstance(provider, dict) else None)
            or urlparse(link or "").hostname
        )
        if title and link:
            result.append(
                {
                    "title": title,
                    "url": link,
                    "source": str(source)[:100],
                    "published_at": None if date_only else stamp.isoformat(),
                    "publication_date": stamp.date().isoformat(),
                    "time_basis": "SOURCE_DATE_ONLY"
                    if date_only
                    else "SOURCE_TIMESTAMP",
                }
            )
    return sorted(
        result, key=lambda x: x["published_at"] or x["publication_date"], reverse=True
    )[:8]


class StockReportService:
    def __init__(
        self,
        technical_getter,
        *,
        company_provider=None,
        news_getter=None,
        market_label="Kite Connect",
        quote_getter=None,
    ):
        self.technical_getter = technical_getter
        self.company = company_provider or CompanyReportProvider()
        self.news_getter = news_getter
        self.market_label = market_label
        self.quote_getter = quote_getter
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def build(
        self,
        symbol,
        *,
        horizon="short_term",
        strategy_id=None,
        now=None,
        force_refresh=False,
    ):
        now = now or datetime.now(TZ)
        if now.tzinfo is None:
            raise ValueError("Report time requires a timezone")
        symbol = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9&._-]{0,29}", symbol) or ".." in symbol:
            raise ValueError("Choose a valid NSE symbol")
        if horizon not in DEFAULTS:
            raise ValueError("Choose Short Term or Long Term")
        settings = horizon_strategy(horizon, strategy_id or DEFAULTS[horizon])
        definition = get_strategy(settings["strategy_id"])
        from services.trading_calendar import latest_completed_session

        key = (symbol, horizon, settings["strategy_id"], latest_completed_session(now))
        with self._lock:
            cached = self._cache.get(key)
            if cached and not force_refresh and time.monotonic() - cached[0] < 300:
                return deepcopy(cached[1])
            result = self._build(symbol, settings, definition, now)
            self._cache[key] = (time.monotonic(), deepcopy(result))
            while len(self._cache) > 32:
                self._cache.popitem(last=False)
            return result

    def _build(self, symbol, settings, definition, now):
        technical = {"signal": "UNAVAILABLE", "data_status": "UNAVAILABLE"}
        candles = []
        market_error = None
        try:
            service = self.technical_getter()
            scan = service.scan(
                symbols=[symbol],
                mode=settings["mode"],
                strategy_id=settings["strategy_id"],
                period=settings["period"],
                execute_paper=False,
                notify_paper=False,
                include_report_evidence=True,
                now=now,
                horizon=settings["horizon"],
            )
            technical = next(
                (row for row in scan.get("results", []) if row.get("symbol") == symbol),
                technical,
            )
        except Exception as exc:
            LOG.warning(
                "stock_report_scan_unavailable error_type=%s", type(exc).__name__
            )
            market_error = provider_detail(type(exc).__name__)
        captured = technical.pop("_report_evidence", None)
        assessed = {
            "status": "UNAVAILABLE",
            "score": None,
            "max_score": 60,
            "reason": "Completed daily technical evidence is unavailable",
        }
        if captured is not None:
            candles = captured["candles"]
            assessed = captured["technical_assessment"]
            technical["indicators"] = {
                **captured["indicators"],
                **(technical.get("indicators") or {}),
            }
        else:
            # A failed scan must not suppress independent price/source diagnostics.
            try:
                from scanner.weekly_floor import daily_history
                from services.institutional_stock_rating import (
                    assess_technical,
                    technical_evidence,
                )

                service = self.technical_getter()
                raw = service.market_data.candles(symbol, period="5y", interval="1d")
                daily = daily_history(raw, now=now)
                assessed = assess_technical(
                    technical_evidence(
                        daily,
                        horizon=settings["horizon"],
                        now=now,
                    ),
                    horizon=settings["horizon"],
                    now=now,
                )
                for stamp, row in daily.tail(252).iterrows():
                    values = {
                        name: finite(row.get(name))
                        for name in (
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                        )
                    }
                    if all(v is not None for v in values.values()):
                        candles.append(
                            {"date": pd.Timestamp(stamp).date().isoformat(), **values}
                        )
            except Exception as exc:
                LOG.warning(
                    "stock_report_chart_unavailable error_type=%s", type(exc).__name__
                )
                market_error = market_error or provider_detail(type(exc).__name__)
        if technical.get("signal") == "ERROR" or technical.get("data_status") in {
            "UNAVAILABLE",
            "STALE",
            "WARMING_UP",
        }:
            row_error = {
                key: technical.get(key)
                for key in (
                    "data_status",
                    "data_code",
                    "data_reason",
                    "retryable",
                )
            }
            market_error = (
                row_error if row_error.get("data_code") else market_error
            ) or provider_detail("missing completed candles")
        try:
            company = self.company.get(symbol, today=now.astimezone(TZ).date())
        except Exception:
            company = {
                "status": "unavailable",
                "metrics": {},
                "annual": [],
                "quarterly": [],
                "shareholding": [],
            }
        news = []
        news_status = "unavailable"
        if self.news_getter:
            try:
                news = news_rows(self.news_getter().news(symbol), now)
                news_status = "available" if news else "no_recent_dated_items"
            except Exception:
                pass
        plan = technical.get("entry_plan") or {}
        rating = technical.get("institutional_rating") or {}
        close = candles[-1]["close"] if candles else None
        levels = plan.get("pivot_levels") or plan.get("entry_pivots") or {}
        if not levels:
            indicators = technical.get("indicators") or {}
            levels = {
                name: finite(indicators.get("FIB_YEAR_" + name))
                for name in ("P", "S1", "S2", "S3", "R1", "R2", "R3")
            }
        levels = {
            k: value
            for k, v in levels.items()
            if (value := finite(v)) is not None and value > 0
        }
        support = max((v for v in levels.values() if close and v < close), default=None)
        resistance = min(
            (v for v in levels.values() if close and v > close), default=None
        )
        entry = finite(plan.get("entry") or technical.get("entry"))
        stop = finite(plan.get("stoploss") or technical.get("stoploss"))
        targets = [
            finite(plan.get("partial_target")),
            finite(plan.get("second_target")),
            finite(plan.get("target2") or technical.get("target2")),
        ]
        ready = (
            definition.get("paper_eligible") is True
            and technical.get("signal") == "BUY"
            and technical.get("data_status") == "READY"
            and market_error is None
            and bool(candles)
            and entry is not None
            and stop is not None
            and 0 < stop < entry
        )
        quote = {"status": "unavailable", "last_price": None, "timestamp": None}
        if self.quote_getter:
            try:
                raw_quote = self.quote_getter().quote(["NSE:" + symbol])[
                    "NSE:" + symbol
                ]
                stamp = pd.Timestamp(raw_quote.get("timestamp"))
                if pd.isna(stamp):
                    raise ValueError("Quote timestamp is unavailable")
                stamp = (
                    stamp.tz_localize(TZ)
                    if stamp.tzinfo is None
                    else stamp.tz_convert(TZ)
                )
                price = finite(raw_quote.get("last_price"))
                if price is None or price <= 0 or (stamp - now).total_seconds() > 5:
                    raise ValueError("Quote is invalid")
                quote = {
                    "status": "observed",
                    "last_price": price,
                    "timestamp": stamp.isoformat(),
                    "fresh_for_order": False,
                }
            except Exception:
                pass
        conditional = conditional_plan(candles, horizon=settings["horizon"])
        if candles and conditional.get("entry") is not None:
            from services.trading_calendar import latest_completed_session

            if pd.Timestamp(candles[-1]["date"]).date() != latest_completed_session(
                now
            ):
                conditional["status"] = "STALE_REFERENCE"
                conditional["data_note"] = (
                    "These dated reference levels require updated "
                    "completed candles before use."
                )
            elif market_error:
                conditional["data_note"] = (
                    "The selected strategy is unavailable or unconfirmed; "
                    "independent price references do not grant entry eligibility."
                )
        bullets = self._overview(technical, candles, settings["strategy_id"])
        if market_error:
            bullets.append(market_error["data_reason"])
        from services.evaluation_diagnostics import diagnostics
        from services.strategy_provenance import identity

        evaluation = diagnostics(technical)
        for component, available, code, reason, stamp in (
            (
                "LTP",
                quote.get("last_price") is not None,
                "QUOTE_UNAVAILABLE",
                (
                    "No dated broker quote was recorded. A "
                    "daily close is not a current LTP."
                ),
                quote.get("timestamp"),
            ),
            (
                "Company data",
                company.get("status") == "available",
                "COMPANY_DATA_UNAVAILABLE",
                "Company metrics are unavailable from the configured source.",
                company.get("as_of"),
            ),
            (
                "News",
                bool(news),
                "NO_RECENT_DATED_NEWS",
                "No recent dated news evidence was returned by the configured source.",
                None,
            ),
        ):
            evaluation.append(
                {
                    "component": component,
                    "status": "AVAILABLE" if available else "UNAVAILABLE",
                    "code": "EVIDENCE_AVAILABLE" if available else code,
                    "reason": (
                        "Dated source evidence is available; availability does not "
                        "imply execution readiness."
                    )
                    if available
                    else reason,
                    "as_of": stamp,
                    "source": "configured_source",
                }
            )
        return {
            "schema_version": "stock-report-v1",
            "symbol": symbol,
            "company_name": company.get("company_name") or symbol,
            "generated_at": now.astimezone(UTC).isoformat(),
            "registry_version": REGISTRY_VERSION,
            "strategy_provenance": identity(
                {
                    "strategy_id": settings["strategy_id"],
                    "registry_version": REGISTRY_VERSION,
                    "exit_policy_version": technical.get("exit_policy_version"),
                },
                plan=plan,
            ),
            "evaluation_diagnostics": evaluation,
            "horizon": settings["horizon"],
            "strategy": readable_rules(definition, settings["horizon"]),
            "price": {
                "value": close,
                "basis": "Last completed daily close",
                "bar_date": candles[-1]["date"] if candles else None,
                "source": self.market_label,
            },
            "market_quote": quote,
            "conditional_plan": conditional,
            "technical": technical,
            "market_error": market_error,
            "rating": rating,
            "technical_assessment": assessed,
            "trade_plan": {
                "entry": entry,
                "stop_reference": stop,
                "stop_is_resting_order": plan.get("stop_is_resting_order"),
                "targets": targets,
                "support": support,
                "resistance": resistance,
                "pivot_levels": levels,
                "entry_order_type": plan.get("entry_order_type"),
                "reviewable_setup": ready,
                "execution_enabled": False,
                "status": "DATA_UNAVAILABLE"
                if market_error or technical.get("data_status") != "READY"
                else "EXIT_SIGNAL"
                if technical.get("signal") == "EXIT"
                else "ARMED"
                if technical.get("signal") == "BUY" and entry is not None
                else "WAITING_CONFIRMATION"
                if entry is not None
                else "NO_VALID_ENTRY_PLAN",
                "conditions": [
                    {"condition": key, "passed": value}
                    for key, value in (
                        technical.get("technical_evidence") or {}
                    ).items()
                    if isinstance(value, bool)
                ],
                "indicator_references": {
                    key: value
                    for key, raw in (technical.get("indicators") or {}).items()
                    if key.startswith(("EMA_", "VWMA_", "FIB_YEAR_"))
                    and (value := finite(raw)) is not None
                },
            },
            "candles": candles,
            "company": company,
            "news": news,
            "news_status": news_status,
            "overview": bullets,
            "risk_notes": [
                (
                    "Approved strategy levels and independent conditional references "
                    "are labelled separately. Neither permits automated entry without "
                    "current strategy confirmation and risk admission."
                ),
                (
                    "Daily candles cannot establish intrabar exec"
                    "ution or a fresh tradable quote."
                ),
                (
                    "Use only the exit conditions shown for this "
                    "strategy. A plotted reference alone is not a"
                    " resting stop order."
                ),
            ],
            "broker_orders_allowed": False,
        }

    @staticmethod
    def _overview(technical, candles, strategy_id):
        signal = technical.get("signal", "UNAVAILABLE")
        messages = [f"Selected strategy signal: {signal}."]
        if technical.get("data_reason"):
            messages.append(str(technical["data_reason"]))
        if candles:
            messages.append(
                f"The price chart contains {len(candles)} "
                f"completed daily candles through "
                f"{candles[-1]['date']}."
            )
        indicators = technical.get("indicators") or {}
        rsi = finite(indicators.get("RSI_WILDER_14"))
        if rsi is not None:
            messages.append(
                f"Wilder RSI(14) is {rsi:.2f}. Momentum is "
                f"evaluated using the selected strategy's "
                f"approved threshold."
            )
        family = "VWMA" if "vwma" in strategy_id else "EMA"
        pair = (
            (20, 50)
            if "vwma20_50" in strategy_id
            else (9, 26)
            if family == "VWMA"
            else (50, 100)
            if "50_100" in strategy_id
            else (100, 200)
            if "100_200" in strategy_id
            else (20, 50)
        )
        fast_name, slow_name = (f"{family}_{length}" for length in pair)
        fast = finite(indicators.get(fast_name))
        slow = finite(indicators.get(slow_name))
        if fast is not None and slow is not None:
            relation = (
                "above" if fast > slow else "below" if fast < slow else "equal to"
            )
            messages.append(
                f"{family}{pair[0]} is {fast:.2f}, {relation} "
                f"{family}{pair[1]} at "
                f"{slow:.2f}; the selected strategy still "
                f"controls the entry trigger."
            )
        volume = finite(indicators.get("volume"))
        average = finite(indicators.get("VOL_SMA_20"))
        if volume is not None and average is not None and average > 0:
            messages.append(
                f"Completed candle volume is "
                f"{volume / average:.2f} times its 20-period "
                f"simple average."
            )
        return messages
