"""TrendForge Corporate Action Service."""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta

from providers import CorporateActionProvider, NSECorporateActionProvider

logger = logging.getLogger(__name__)


class CorporateActionService:
    CACHE_TTL = 3600
    EVENT_SCORES = {
        "BONUS": 8, "STOCK SPLIT": 7, "SPLIT": 7, "DIVIDEND": 5,
        "BUYBACK": 9, "RIGHTS": 3, "MERGER": 8, "DEMERGER": 7,
        "ACQUISITION": 8, "BOARD MEETING": 2, "AGM": 1, "EGM": 1,
        "RESULT": 4, "EARNINGS": 4, "PREFERENTIAL ISSUE": 2,
        "PENALTY": -6, "DEFAULT": -8, "INSOLVENCY": -10,
        "DELISTING": -10, "DOWNGRADE": -6, "RESIGNATION": -3,
    }

    def __init__(self, provider: CorporateActionProvider | None = None):
        self.provider = provider or NSECorporateActionProvider()
        self.cache = {}
        self.lock = threading.Lock()

    def _cache_get(self, key):
        item = self.cache.get(key)
        if item is None:
            return None
        value, timestamp = item
        if time.time() - timestamp > self.CACHE_TTL:
            self.cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key, value):
        self.cache[key] = (value, time.time())

    @staticmethod
    def _contains_symbol(item, symbol: str) -> bool:
        symbol = symbol.upper()
        for key in ("symbol", "symbols", "ticker", "security", "companyName",
                    "company", "securityName"):
            value = item.get(key) if isinstance(item, dict) else None
            if symbol in str(value or "").upper():
                return True
        return symbol in str(item).upper()

    def get_actions(self, symbol: str, force_refresh=False):
        symbol = symbol.upper()
        if not force_refresh:
            cached = self._cache_get(symbol)
            if cached is not None:
                return cached
        actions = []
        try:
            for item in self.provider.corporate_actions() or []:
                if not self._contains_symbol(item, symbol):
                    continue
                item = dict(item) if isinstance(item, dict) else {"raw": item}
                subject = item.get("subject", "")
                purpose = item.get("purpose", "")
                action = {
                    "symbol": symbol, "subject": subject, "purpose": purpose,
                    "date": item.get("date", ""), "details": item,
                }
                action["score"] = self.score_action(subject + " " + purpose)
                actions.append(action)
        except Exception:
            logger.exception("Unable to fetch corporate actions.")
        self._cache_set(symbol, actions)
        return actions

    def score_action(self, text: str) -> int:
        score = sum(weight for event, weight in self.EVENT_SCORES.items()
                     if event in text.upper())
        return max(-10, min(score, 10))

    def calculate_action_score(self, symbol: str) -> int:
        actions = self.get_actions(symbol)
        return round(sum(a["score"] for a in actions) / len(actions)) if actions else 0

    def upcoming_actions(self, days=30):
        result = []
        limit = datetime.today() + timedelta(days=days)
        try:
            for item in self.provider.corporate_actions() or []:
                date_str = item.get("date") if isinstance(item, dict) else None
                if not date_str:
                    continue
                event_date = None
                for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
                    try:
                        event_date = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        pass
                if event_date and datetime.today() <= event_date <= limit:
                    result.append(item)
        except Exception:
            logger.exception("Unable to fetch upcoming actions.")
        return result

    def has_upcoming_event(self, symbol, days=15) -> bool:
        return any(self._contains_symbol(item, symbol) for item in self.upcoming_actions(days))

    def refresh(self, symbols):
        for symbol in symbols:
            self.get_actions(symbol, force_refresh=True)

    def market_summary(self, symbols):
        scores = defaultdict(int)
        for symbol in symbols:
            scores[symbol] = self.calculate_action_score(symbol)
        average = round(sum(scores.values()) / len(scores), 2) if scores else 0
        return {"average_score": average, "stocks": dict(scores)}

    def high_impact_events(self, symbols, threshold=7):
        return [
            action for symbol in symbols
            for action in self.get_actions(symbol)
            if abs(action["score"]) >= threshold
        ]


corporate_action_service = CorporateActionService()
