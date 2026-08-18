"""
TrendForge v2 - Corporate Action & Event Engine

Purpose
-------
Evaluates corporate events that can materially affect short-term and
swing-trading decisions.

Covered events
--------------
- Results / earnings
- Dividend
- Bonus
- Split
- Rights issue
- Buyback
- Merger / demerger
- Acquisition / divestment
- Fund raising
- Preferential issue
- QIP
- OFS
- Promoter transactions
- Pledge / release of pledge
- Delisting / suspension
- Board meetings
- Regulatory / legal events
- Rating actions
- Order wins / cancellations

Principles
----------
1. Never invent an event.
2. Missing event data lowers confidence.
3. Event score is directional, not a standalone trade signal.
4. Near-term material events receive higher weight.
5. Negative hard-risk events can veto a BUY candidate.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from engines.base_engine import BaseEngine, EngineResult
from engines.corporate_action_contract import CorporateActionInputContract


class CorporateActionEngine(BaseEngine):
    NAME = "Corporate Action Engine"
    priority = 4
    mandatory = False

    MAX_POSITIVE = 65.0
    MAX_NEGATIVE = 100.0

    POSITIVE_TYPES = {"dividend": 5.0, "special_dividend": 7.0, "bonus": 4.0, "split": 2.0, "buyback": 8.0, "rights_issue": 2.0, "qip": 3.0, "fund_raise": 3.0, "order_win": 8.0, "large_order": 8.0, "acquisition": 5.0, "divestment": 4.0, "demerger": 4.0, "rating_upgrade": 5.0, "pledge_release": 6.0, "promoter_buy": 8.0, "board_approval": 2.0}
    NEGATIVE_TYPES = {"earnings_miss": -12.0, "profit_warning": -15.0, "guidance_cut": -12.0, "dividend_cut": -8.0, "dividend_cancelled": -10.0, "dilution": -8.0, "preferential_issue": -5.0, "ofs": -6.0, "promoter_sell": -10.0, "pledge_increase": -12.0, "order_cancelled": -12.0, "order_loss": -10.0, "acquisition_risk": -5.0, "regulatory": -15.0, "legal": -15.0, "fraud": -30.0, "default": -30.0, "insolvency": -35.0, "bankruptcy": -40.0, "delisting": -35.0, "suspension": -40.0, "rating_downgrade": -12.0}
    HARD_NEGATIVE = {"fraud", "default", "insolvency", "bankruptcy", "delisting", "suspension"}
    TYPE_ALIASES = {"results": "earnings", "quarterly_results": "earnings", "financial_results": "earnings", "earnings": "earnings", "dividend": "dividend", "special dividend": "special_dividend", "bonus": "bonus", "bonus issue": "bonus", "stock split": "split", "split": "split", "buyback": "buyback", "share buyback": "buyback", "rights": "rights_issue", "rights issue": "rights_issue", "qip": "qip", "fund raising": "fund_raise", "fundraise": "fund_raise", "preferential": "preferential_issue", "preferential issue": "preferential_issue", "ofs": "ofs", "offer for sale": "ofs", "merger": "merger", "demerger": "demerger", "acquisition": "acquisition", "divestment": "divestment", "order win": "order_win", "order": "order_win", "order cancellation": "order_cancelled", "order cancelled": "order_cancelled", "pledge": "pledge_increase", "pledge increase": "pledge_increase", "pledge release": "pledge_release", "promoter buy": "promoter_buy", "promoter purchase": "promoter_buy", "promoter sell": "promoter_sell", "rating upgrade": "rating_upgrade", "rating downgrade": "rating_downgrade", "regulatory": "regulatory", "legal": "legal", "fraud": "fraud", "default": "default", "insolvency": "insolvency", "bankruptcy": "bankruptcy", "delisting": "delisting", "suspension": "suspension"}
    POSITIVE_TERMS = ("order win", "large order", "major order", "contract win", "buyback", "special dividend", "dividend declared", "bonus declared", "rating upgrade", "pledge released", "promoter bought", "promoter purchase", "acquisition approved", "demerger approved", "fund raise approved")
    NEGATIVE_TERMS = ("profit warning", "guidance cut", "order cancelled", "order cancellation", "rating downgrade", "pledge increased", "promoter sold", "fraud", "default", "insolvency", "bankruptcy", "delisting", "suspension", "regulatory action", "legal action")

    def __init__(self, provider=None, repository=None, input_contract=None):
        self.provider = provider
        self.repository = repository
        self.input_contract = input_contract or CorporateActionInputContract()
        self._discover_dependencies()

    def evaluate(self, stock: Any) -> EngineResult:
        report = self.input_contract.validate(stock if isinstance(stock, Mapping) else {})
        if not report.ready:
            return EngineResult(engine=self.NAME, passed=False, score=0.0, max_score=100.0, confidence=0.0, grade="N/A", reasons=[], warnings=["Corporate action input contract failed"], metrics={"input_contract": report.as_dict()})
        payload = self._normalise(stock)
        symbol = self._symbol(payload, stock)
        events = self._collect_events(symbol, payload)
        scored, positive, negative, hard_block = [], 0.0, 0.0, False
        for event in events:
            item = self._score_event(event)
            scored.append(item)
            if item["score"] > 0: positive += item["score"]
            else: negative += abs(item["score"])
            hard_block = hard_block or item["hard_negative"]
        positive, negative = min(self.MAX_POSITIVE, positive), min(self.MAX_NEGATIVE, negative)
        score = self._clamp(50.0 + positive - negative, 0.0, 100.0)
        data_quality = self._data_quality(events)
        confidence = self._confidence(events, data_quality)
        bias = self._bias(positive, negative)
        reasons, warnings = self._reasons(scored), self._warnings(scored)
        if not events: warnings.append("No corporate-event data available.")
        return EngineResult(engine=self.NAME, passed=score >= 55.0 and not hard_block, score=round(score, 2), max_score=100.0, confidence=round(confidence, 2), grade=self._grade(score), reasons=self._dedupe(reasons)[:30], warnings=self._dedupe(warnings)[:30], metrics={"symbol": symbol, "event_count": len(events), "positive_event_score": round(positive, 2), "negative_event_score": round(negative, 2), "bias": bias, "hard_block": hard_block, "data_quality": data_quality, "events": scored[:50], "near_term_events": sum(1 for e in scored if e["time_bucket"] == "near_term"), "material_events": sum(1 for e in scored if e["material"])})

    def _discover_dependencies(self):
        if self.provider is None:
            for module_name, class_name in (("providers.nse_provider", "NSEProvider"), ("providers.corporate_action_provider", "CorporateActionProvider")):
                try:
                    module = __import__(module_name, fromlist=[class_name]); cls = getattr(module, class_name, None)
                    if cls is not None: self.provider = cls(); break
                except Exception: continue
        if self.repository is None:
            try:
                from database.repositories.corporate_repository import CorporateRepository
                self.repository = CorporateRepository()
            except Exception: pass

    def _collect_events(self, symbol, payload):
        raw = []
        for key in ("corporate_actions", "corporate_events", "events", "corporate_action"):
            value = payload.get(key)
            if value: raw.extend(self._rows(value))
        if self.provider is not None:
            for name in ("get_corporate_actions", "get_corporate_events", "get_events", "fetch_corporate_actions"):
                method = getattr(self.provider, name, None)
                if callable(method):
                    try:
                        value = method(symbol)
                        if value: raw.extend(self._rows(value)); break
                    except Exception: continue
        if self.repository is not None:
            for name in ("get_by_symbol", "get_corporate_actions", "by_symbol"):
                method = getattr(self.repository, name, None)
                if callable(method):
                    try:
                        value = method(symbol)
                        if value: raw.extend(self._rows(value)); break
                    except Exception: continue
        normalized, seen = [], set()
        for row in raw:
            event = self._normalize_event(row); fingerprint = self._fingerprint(event)
            if fingerprint not in seen: seen.add(fingerprint); normalized.append(event)
        return normalized

    @staticmethod
    def _normalise(stock):
        if isinstance(stock, Mapping): return dict(stock)
        if is_dataclass(stock):
            try: return asdict(stock)
            except Exception: pass
        if hasattr(stock, "__dict__"):
            try: return dict(vars(stock))
            except Exception: pass
        return {}

    @staticmethod
    def _symbol(payload, stock):
        if isinstance(stock, str): return stock.strip().upper()
        return str(payload.get("symbol") or payload.get("ticker") or payload.get("tradingsymbol") or "").strip().upper()

    @classmethod
    def _rows(cls, value):
        if value is None: return []
        if isinstance(value, Mapping):
            for key in ("data", "results", "items", "rows", "events", "corporate_actions"):
                nested = value.get(key)
                if isinstance(nested, (list, tuple)): return [cls._to_dict(x) for x in nested]
            return [dict(value)]
        if isinstance(value, (list, tuple, set)): return [cls._to_dict(x) for x in value]
        return []

    @staticmethod
    def _to_dict(value):
        if isinstance(value, Mapping): return dict(value)
        if is_dataclass(value):
            try: return asdict(value)
            except Exception: return {}
        if hasattr(value, "__dict__"):
            try: return dict(vars(value))
            except Exception: return {}
        return {}

    def _normalize_event(self, row):
        title = str(row.get("title") or row.get("headline") or row.get("description") or row.get("event") or row.get("name") or "").strip()
        raw_type = str(row.get("type") or row.get("event_type") or row.get("category") or "").strip().lower()
        event_type = self._canonical_type(raw_type, title)
        return {"type": event_type, "title": title, "date": self._event_date(row), "ex_date": self._date_from(row.get("ex_date") or row.get("exDate")), "record_date": self._date_from(row.get("record_date") or row.get("recordDate")), "amount": self._number(row.get("amount") or row.get("value") or row.get("value_crore") or row.get("transaction_value")), "percent": self._number(row.get("percent") or row.get("percentage") or row.get("change_percent")), "status": str(row.get("status") or row.get("action") or "").strip().lower(), "raw": dict(row)}

    def _canonical_type(self, raw_type, title):
        normalized = re.sub(r"\s+", " ", raw_type.lower().strip())
        if normalized in self.TYPE_ALIASES: return self.TYPE_ALIASES[normalized]
        text = f"{normalized} {title.lower()}"
        for alias, canonical in self.TYPE_ALIASES.items():
            if alias in text: return canonical
        if any(term in text for term in self.POSITIVE_TERMS):
            if "buyback" in text: return "buyback"
            if "dividend" in text: return "dividend"
            if "pledge" in text: return "pledge_release"
            if "rating" in text: return "rating_upgrade"
            if "order" in text: return "order_win"
        if any(term in text for term in self.NEGATIVE_TERMS):
            if "fraud" in text: return "fraud"
            if "default" in text: return "default"
            if "insolvency" in text: return "insolvency"
            if "bankruptcy" in text: return "bankruptcy"
            if "delisting" in text: return "delisting"
            if "suspension" in text: return "suspension"
            if "pledge" in text: return "pledge_increase"
            if "promoter" in text and "sold" in text: return "promoter_sell"
            if "rating" in text: return "rating_downgrade"
            if "order" in text and "cancel" in text: return "order_cancelled"
        return "default"

    @staticmethod
    def _number(value):
        try: return float(value)
        except (TypeError, ValueError): return None

    @staticmethod
    def _date_from(value):
        if isinstance(value, datetime): return value.date()
        if isinstance(value, date): return value
        if not value: return None
        try: return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except Exception:
            try: return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
            except Exception: return None

    def _event_date(self, row):
        for key in ("date", "event_date", "eventDate", "announcement_date", "announcementDate"):
            value = self._date_from(row.get(key))
            if value: return value
        return None

    def _score_event(self, event):
        event_type = event["type"]
        score = self.POSITIVE_TYPES.get(event_type, self.NEGATIVE_TYPES.get(event_type, 0.0))
        if event["date"]:
            days = (event["date"] - date.today()).days
        else: days = None
        bucket = "near_term" if days is not None and 0 <= days <= 30 else "recent" if days is not None and -30 <= days < 0 else "future" if days is not None and days > 30 else "unknown"
        material = abs(score) >= 8.0
        hard_negative = event_type in self.HARD_NEGATIVE
        return {"type": event_type, "title": event["title"], "score": score, "days_to_event": days, "time_bucket": bucket, "material": material, "hard_negative": hard_negative}

    @staticmethod
    def _data_quality(events):
        if not events: return 0.0
        dated = sum(1 for e in events if e.get("date")) / len(events)
        typed = sum(1 for e in events if e.get("type") != "default") / len(events)
        return round((dated * 0.5 + typed * 0.5) * 100, 2)

    @staticmethod
    def _confidence(events, quality):
        if not events: return 20.0
        return min(100.0, round(20.0 + quality * 0.8, 2))

    @staticmethod
    def _bias(positive, negative):
        if positive > negative * 1.25: return "positive"
        if negative > positive * 1.25: return "negative"
        return "neutral"

    @staticmethod
    def _grade(score):
        return "A+" if score >= 90 else "A" if score >= 80 else "B" if score >= 70 else "C" if score >= 60 else "D"

    @staticmethod
    def _clamp(value, low, high): return max(low, min(high, value))

    @staticmethod
    def _fingerprint(event): return (event.get("type"), event.get("title"), event.get("date"), event.get("ex_date"), event.get("record_date"))

    @staticmethod
    def _dedupe(items): return list(dict.fromkeys(str(x) for x in items if x))

    @staticmethod
    def _reasons(scored): return [f"{e['type']}: {e['title']}" for e in scored if e["score"] > 0]

    @staticmethod
    def _warnings(scored): return [f"Negative event: {e['title']}" for e in scored if e["score"] < 0]


__all__ = ["CorporateActionEngine"]
