"""TrendForge News Service."""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Dict, List

from providers import CompositeNewsProvider, NewsProvider

# Explicit legacy provider seam retained during migration: yfinance_provider / nse_provider.
from database.repositories.news_repository import NewsRepository

logger = logging.getLogger(__name__)


class NewsService:
    CACHE_TTL = 300
    POSITIVE_KEYWORDS = {"order", "contract", "approval", "acquisition", "buyback", "growth", "profit", "record", "upgrade", "expansion", "partnership", "wins", "strong", "bonus", "dividend", "breakout", "beat"}
    NEGATIVE_KEYWORDS = {"fraud", "penalty", "downgrade", "loss", "decline", "lawsuit", "default", "bankruptcy", "investigation", "warning", "fall", "crash", "weak", "miss", "fire", "resigns"}
    BREAKING_KEYWORDS = {"results", "earnings", "merger", "acquisition", "buyback", "split", "dividend", "bulk deal", "block deal", "order", "contract", "approval"}

    def __init__(self, provider: NewsProvider | None = None):
        self.provider = provider or CompositeNewsProvider()
        self.repo = NewsRepository()
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

    def get_news(self, symbol: str, force_refresh=False) -> List[Dict]:
        key = symbol.upper()
        if not force_refresh:
            cached = self._cache_get(key)
            if cached is not None:
                return cached
        news = []
        try:
            for item in self.provider.news(symbol) or []:
                news.append({
                    "title": item.get("title") or item.get("subject"),
                    "publisher": item.get("publisher") or item.get("source"),
                    "link": item.get("link", ""),
                    "published": item.get("providerPublishTime") or item.get("date"),
                    "source": item.get("source", "Yahoo" if "publisher" in item else "NSE"),
                })
        except Exception as e:
            logger.exception(e)
        news = self.remove_duplicates(news)
        for item in news:
            item["sentiment"] = self.sentiment(item["title"] or "")
            item["score"] = self.score_news(item["title"] or "")
        self._cache_set(key, news)
        return news

    def remove_duplicates(self, news: List[Dict]) -> List[Dict]:
        unique = {}
        for item in news:
            title = (item.get("title") or "").strip().lower()
            if title not in unique:
                unique[title] = item
        return list(unique.values())

    def sentiment(self, title: str) -> str:
        score = self.score_news(title)
        if score > 1:
            return "Positive"
        if score < -1:
            return "Negative"
        return "Neutral"

    def score_news(self, text: str) -> int:
        text = text.lower()
        score = sum(2 for word in self.POSITIVE_KEYWORDS if word in text)
        score -= sum(2 for word in self.NEGATIVE_KEYWORDS if word in text)
        return max(-10, min(score, 10))

    def calculate_news_score(self, symbol: str) -> int:
        news = self.get_news(symbol)
        if not news:
            return 0
        return round(sum(n["score"] for n in news) / len(news))

    def has_breaking_news(self, symbol) -> bool:
        return any(keyword in (item.get("title") or "").lower() for item in self.get_news(symbol) for keyword in self.BREAKING_KEYWORDS)

    def latest_news(self, symbols: List[str]) -> Dict:
        return {symbol: self.get_news(symbol) for symbol in symbols}

    def save_news(self, symbol: str):
        for item in self.get_news(symbol):
            try:
                self.repo.insert_news(symbol=symbol, title=item["title"], source=item["source"], publisher=item["publisher"], sentiment=item["sentiment"], score=item["score"], published=item["published"], url=item["link"])
            except Exception:
                logger.exception("Unable to save news.")

    def refresh(self, symbols: List[str]):
        for symbol in symbols:
            try:
                self.get_news(symbol, force_refresh=True)
            except Exception:
                logger.exception(symbol)

    def market_sentiment(self, symbols: List[str]) -> Dict:
        scores = defaultdict(int)
        for symbol in symbols:
            scores[symbol] = self.calculate_news_score(symbol)
        avg = round(sum(scores.values()) / len(scores), 2) if scores else 0
        return {"average_score": avg, "stocks": dict(scores)}


news_service = NewsService()
