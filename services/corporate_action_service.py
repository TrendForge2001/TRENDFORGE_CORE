"""TrendForge Corporate Action Service."""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

from providers import CorporateActionProvider, NSECorporateActionProvider
from database.repositories.corporate_repository import CorporateRepository

logger = logging.getLogger(__name__)


class CorporateActionService:
    CACHE_TTL = 3600
    EVENT_SCORES = {"BONUS": 8, "STOCK SPLIT": 7, "SPLIT": 7, "DIVIDEND": 5, "BUYBACK": 9, "RIGHTS": 3, "MERGER": 8, "DEMERGER": 7, "ACQUISITION": 8, "BOARD MEETING": 2, "AGM": 1, "EGM": 1, "RESULT": 4, "EARNINGS": 4, "PREFERENTIAL ISSUE": 2, "PENALTY": -6, "DEFAULT": -8, "INSOLVENCY": -10, "DELISTING": -10, "DOWNGRADE": -6, "RESIGNATION": -3}

    def __init__(self, provider: CorporateActionProvider | None = None):
        self.provider = provider or NSECorporateActionProvider()
        self.repo = CorporateRepository()
        self.cache = {}
        self.lock = threading.Lock()

    def _cache_get(self, key):
        if key not in self.cache:
            return None
        value, ts = self.cache[key]
        if time.time() - ts > self.CACHE_TTL:
            del self.cache[key]
            return None
        return value

    def _cache_set(self, key, value):
        self.cache[key] = (value, time.time())

    def get_actions(self, symbol: str, force_refresh=False) -> List[Dict]:
        symbol = symbol.upper()
        if not force_refresh:
            cached = self._cache_get(symbol)
            if cached is not None:
                return cached
        actions = []
        try:
            for item in self.provider.corporate_actions():
                if symbol in str(item).upper():
                    action = {"symbol": symbol, "subject": item.get("subject", ""), "purpose": item.get("purpose", ""), "date": item.get("date", ""), "details": item}
                    action["score"] = self.score_action(action["subject"] + " " + action["purpose"])
                    actions.append(action)
        except Exception as e:
            logger.exception(e)
        self._cache_set(symbol, actions)
        return actions

    def score_action(self, text: str) -> int:
        score = sum(weight for event, weight in self.EVENT_SCORES.items() if event in text.upper())
        return max(-10, min(score, 10))

    def calculate_action_score(self, symbol: str) -> int:
        actions = self.get_actions(symbol)
        return round(sum(a["score"] for a in actions) / len(actions)) if actions else 0

    def upcoming_actions(self, days=30) -> List[Dict]:
        result = []
        limit = datetime.today() + timedelta(days=days)
        try:
            for item in self.provider.corporate_actions():
                date_str = item.get("date")
                if not date_str:
                    continue
                event_date = None
                for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
                    try:
                        event_date = datetime.strptime(date_str, fmt)
                        break
                    except Exception:
                        pass
                if event_date and datetime.today() <= event_date <= limit:
                    result.append(item)
        except Exception:
            logger.exception("Unable to fetch upcoming actions.")
        return result

    def has_upcoming_event(self, symbol, days=15) -> bool:
        return any(symbol.upper() in str(item).upper() for item in self.upcoming_actions(days))

    def save_actions(self, symbol):
        for action in self.get_actions(symbol):
            try:
                self.repo.insert_action(symbol=symbol, subject=action["subject"], purpose=action["purpose"], event_date=action["date"], score=action["score"], raw_data=str(action["details"]))
            except Exception:
                logger.exception("Unable to save corporate action.")

    def refresh(self, symbols: List[str]):
        for symbol in symbols:
            try:
                self.get_actions(symbol, force_refresh=True)
            except Exception:
                logger.exception(symbol)

    def market_summary(self, symbols: List[str]) -> Dict:
        scores = defaultdict(int)
        for symbol in symbols:
            scores[symbol] = self.calculate_action_score(symbol)
        average = round(sum(scores.values()) / len(scores), 2) if scores else 0
        return {"average_score": average, "stocks": dict(scores)}

    def high_impact_events(self, symbols: List[str], threshold=7) -> List[Dict]:
        return [action for symbol in symbols for action in self.get_actions(symbol) if abs(action["score"]) >= threshold]


corporate_action_service = CorporateActionService()
