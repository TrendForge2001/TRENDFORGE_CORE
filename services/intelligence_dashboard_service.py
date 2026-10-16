"""Canonical persisted News + Corporate Actions intelligence service."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from database.repositories.intelligence_event_repository import (
    IntelligenceEventRepository,
)


class IntelligenceDashboardService:
    def __init__(
        self,
        *,
        news_service: Any,
        corporate_action_service: Any,
        repository: IntelligenceEventRepository | None = None,
    ) -> None:
        if news_service is None:
            raise ValueError("news_service is required")
        if corporate_action_service is None:
            raise ValueError("corporate_action_service is required")
        self.news_service = news_service
        self.corporate_action_service = corporate_action_service
        self._owns_repository = repository is None
        self.repository = repository or IntelligenceEventRepository()

    @staticmethod
    def _symbol(value: Any) -> str:
        symbol = str(value or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if len(symbol) > 30:
            raise ValueError("symbol must be 30 characters or fewer")
        return symbol

    @classmethod
    def _symbols(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            symbol = cls._symbol(value)
            if symbol not in seen:
                seen.add(symbol)
                normalized.append(symbol)
        if not normalized:
            raise ValueError("at least one symbol is required")
        if len(normalized) > 50:
            raise ValueError("at most 50 symbols can be refreshed at once")
        return normalized

    @staticmethod
    def _iso_time(value: Any) -> str | None:
        if value in (None, ""):
            return None

        if isinstance(value, (int, float)):
            number = float(value)
            if number > 10_000_000_000:
                number /= 1000.0
            try:
                return datetime.fromtimestamp(
                    number,
                    tz=timezone.utc,
                ).isoformat()
            except (OverflowError, OSError, ValueError):
                return str(value)

        raw = str(value).strip()
        if not raw:
            return None

        for fmt in (
            "%Y-%m-%d",
            "%d-%b-%Y",
            "%d-%m-%Y",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                parsed = datetime.strptime(raw, fmt)
                return parsed.replace(
                    tzinfo=timezone.utc
                ).isoformat()
            except ValueError:
                pass

        try:
            parsed = datetime.fromisoformat(
                raw.replace("Z", "+00:00")
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(
                    tzinfo=timezone.utc
                )
            return parsed.astimezone(
                timezone.utc
            ).isoformat()
        except ValueError:
            return raw

    @staticmethod
    def _key(*parts: Any) -> str:
        material = "|".join(
            str(part or "").strip().lower()
            for part in parts
        )
        return hashlib.sha256(
            material.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _sentiment_score(label: str | None) -> float:
        return {
            "positive": 1.0,
            "negative": -1.0,
            "neutral": 0.0,
        }.get(str(label or "").strip().lower(), 0.0)

    @staticmethod
    def _event_type(
        text: str,
        event_scores: dict[str, int],
    ) -> str:
        upper = str(text or "").upper()
        matches = [
            event
            for event in event_scores
            if event in upper
        ]
        if not matches:
            return "CORPORATE_ACTION"
        return sorted(
            matches,
            key=lambda value: (-len(value), value),
        )[0]

    def readiness(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "news_provider": type(
                getattr(self.news_service, "provider", object())
            ).__name__,
            "corporate_action_provider": type(
                getattr(
                    self.corporate_action_service,
                    "provider",
                    object(),
                )
            ).__name__,
            "persisted_events": self.repository.count(),
            "persisted_news": self.repository.count(
                domain="news"
            ),
            "persisted_corporate_actions": self.repository.count(
                domain="corporate_action"
            ),
            "news_scoring": "keyword_heuristic_v1",
            "corporate_action_scoring": "event_weight_heuristic_v1",
            "ai_sentiment": False,
        }

    def refresh(
        self,
        *,
        symbols: list[str],
        domains: list[str] | None = None,
        days: int = 120,
    ) -> dict[str, Any]:
        resolved_symbols = self._symbols(symbols)
        resolved_domains = [
            str(item).strip().lower()
            for item in (
                domains
                if domains is not None
                else ["news", "corporate_actions"]
            )
        ]
        valid_domains = {"news", "corporate_actions"}
        if (
            not resolved_domains
            or any(
                item not in valid_domains
                for item in resolved_domains
            )
        ):
            raise ValueError(
                "domains must contain news and/or corporate_actions"
            )
        days = int(days)
        if not 1 <= days <= 365:
            raise ValueError("days must be between 1 and 365")

        summary: dict[str, Any] = {
            "status": "completed",
            "symbols": resolved_symbols,
            "domains": resolved_domains,
            "days": days,
            "news_events": 0,
            "corporate_action_events": 0,
            "symbol_results": {},
        }

        for symbol in resolved_symbols:
            per_symbol = {
                "news_events": 0,
                "corporate_action_events": 0,
            }

            if "news" in resolved_domains:
                items = self.news_service.get_news(
                    symbol,
                    force_refresh=True,
                )
                for item in items or []:
                    title = str(
                        item.get("title") or ""
                    ).strip()
                    if not title:
                        continue
                    published = self._iso_time(
                        item.get("published")
                    )
                    link = str(
                        item.get("link") or ""
                    ).strip()
                    label = str(
                        item.get("sentiment") or "Neutral"
                    ).strip()
                    event_type = (
                        "BREAKING_NEWS"
                        if any(
                            keyword
                            in title.lower()
                            for keyword in getattr(
                                self.news_service,
                                "BREAKING_KEYWORDS",
                                set(),
                            )
                        )
                        else "NEWS"
                    )
                    self.repository.upsert(
                        {
                            "event_key": self._key(
                                "news",
                                symbol,
                                title,
                                published,
                                link,
                            ),
                            "domain": "news",
                            "symbol": symbol,
                            "event_type": event_type,
                            "headline": title,
                            "summary": None,
                            "source": item.get("source"),
                            "publisher": item.get(
                                "publisher"
                            ),
                            "url": link or None,
                            "event_at": published,
                            "sentiment_label": label,
                            "sentiment_score": (
                                self._sentiment_score(
                                    label
                                )
                            ),
                            "impact_score": float(
                                item.get("score") or 0
                            ),
                            "details": {
                                "methodology": (
                                    "keyword_heuristic_v1"
                                )
                            },
                        }
                    )
                    per_symbol["news_events"] += 1
                    summary["news_events"] += 1

            if "corporate_actions" in resolved_domains:
                actions = (
                    self.corporate_action_service.get_actions(
                        symbol,
                        force_refresh=True,
                        days=days,
                    )
                )
                scores = getattr(
                    self.corporate_action_service,
                    "EVENT_SCORES",
                    {},
                )
                for item in actions or []:
                    subject = str(
                        item.get("subject") or ""
                    ).strip()
                    purpose = str(
                        item.get("purpose") or ""
                    ).strip()
                    event_at = self._iso_time(
                        item.get("date")
                    )
                    combined = " ".join(
                        value
                        for value in (subject, purpose)
                        if value
                    )
                    event_type = self._event_type(
                        combined,
                        scores,
                    )
                    details = item.get("details")
                    details = (
                        dict(details)
                        if isinstance(details, dict)
                        else {}
                    )
                    self.repository.upsert(
                        {
                            "event_key": self._key(
                                "corporate_action",
                                symbol,
                                subject,
                                purpose,
                                event_at,
                            ),
                            "domain": "corporate_action",
                            "symbol": symbol,
                            "event_type": event_type,
                            "headline": (
                                subject
                                or purpose
                                or event_type
                            ),
                            "summary": purpose or None,
                            "source": (
                                details.get("source")
                                or "NSE"
                            ),
                            "publisher": None,
                            "url": (
                                details.get("url")
                                or details.get("link")
                            ),
                            "event_at": event_at,
                            "sentiment_label": None,
                            "sentiment_score": None,
                            "impact_score": float(
                                item.get("score") or 0
                            ),
                            "details": {
                                **details,
                                "methodology": (
                                    "event_weight_heuristic_v1"
                                ),
                            },
                        }
                    )
                    per_symbol[
                        "corporate_action_events"
                    ] += 1
                    summary[
                        "corporate_action_events"
                    ] += 1

            summary["symbol_results"][
                symbol
            ] = per_symbol

        summary["persisted_events"] = self.repository.count()
        return summary

    def events(
        self,
        *,
        domain: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        normalized_domain = None
        if domain:
            normalized_domain = str(domain).strip().lower()
            if normalized_domain == "corporate_actions":
                normalized_domain = "corporate_action"
            if normalized_domain not in {
                "news",
                "corporate_action",
            }:
                raise ValueError(
                    "domain must be news or corporate_action"
                )

        normalized_symbol = (
            self._symbol(symbol)
            if symbol
            else None
        )
        rows = self.repository.list(
            domain=normalized_domain,
            symbol=normalized_symbol,
            limit=limit,
        )
        return {
            "status": "ready",
            "domain": normalized_domain,
            "symbol": normalized_symbol,
            "returned": len(rows),
            "events": rows,
        }

    def news(
        self,
        symbol: str,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        normalized = self._symbol(symbol)
        rows = self.repository.list(
            domain="news",
            symbol=normalized,
            limit=limit,
        )
        positive = sum(
            1
            for item in rows
            if item.get("sentiment_label") == "Positive"
        )
        negative = sum(
            1
            for item in rows
            if item.get("sentiment_label") == "Negative"
        )
        neutral = len(rows) - positive - negative
        breaking = sum(
            1
            for item in rows
            if item.get("event_type") == "BREAKING_NEWS"
        )
        average = (
            sum(
                float(item.get("impact_score") or 0.0)
                for item in rows
            )
            / len(rows)
            if rows
            else 0.0
        )
        return {
            "status": "ready",
            "symbol": normalized,
            "count": len(rows),
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "breaking": breaking,
            "average_impact_score": round(average, 2),
            "latest_fetch_at": self.repository.latest_fetch_at(
                domain="news",
                symbol=normalized,
            ),
            "methodology": "keyword_heuristic_v1",
            "events": rows,
        }

    def corporate_actions(
        self,
        symbol: str,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        normalized = self._symbol(symbol)
        rows = self.repository.list(
            domain="corporate_action",
            symbol=normalized,
            limit=limit,
        )
        high_impact = sum(
            1
            for item in rows
            if abs(float(item.get("impact_score") or 0.0)) >= 7
        )
        now = datetime.now(timezone.utc)
        future_events: list[datetime] = []
        for item in rows:
            raw_time = item.get("event_at")
            if not raw_time:
                continue
            try:
                parsed = datetime.fromisoformat(
                    str(raw_time).replace("Z", "+00:00")
                )
                if parsed.tzinfo is None:
                    parsed = parsed.replace(
                        tzinfo=timezone.utc
                    )
                parsed = parsed.astimezone(timezone.utc)
                if parsed >= now:
                    future_events.append(parsed)
            except ValueError:
                continue
        positive = sum(
            1
            for item in rows
            if float(item.get("impact_score") or 0.0) > 0
        )
        negative = sum(
            1
            for item in rows
            if float(item.get("impact_score") or 0.0) < 0
        )
        average = (
            sum(
                float(item.get("impact_score") or 0.0)
                for item in rows
            )
            / len(rows)
            if rows
            else 0.0
        )
        return {
            "status": "ready",
            "symbol": normalized,
            "count": len(rows),
            "positive_impact": positive,
            "negative_impact": negative,
            "high_impact": high_impact,
            "upcoming": len(future_events),
            "next_event_at": (
                min(future_events).isoformat()
                if future_events
                else None
            ),
            "average_impact_score": round(average, 2),
            "latest_fetch_at": self.repository.latest_fetch_at(
                domain="corporate_action",
                symbol=normalized,
            ),
            "methodology": "event_weight_heuristic_v1",
            "events": rows,
        }

    def summary(self, symbol: str) -> dict[str, Any]:
        normalized = self._symbol(symbol)
        news = self.news(normalized, limit=100)
        actions = self.corporate_actions(
            normalized,
            limit=100,
        )

        news_score = float(
            news.get("average_impact_score") or 0.0
        )
        action_score = float(
            actions.get("average_impact_score") or 0.0
        )
        available: list[tuple[float, float]] = []
        if int(news.get("count") or 0) > 0:
            available.append((news_score, 0.4))
        if int(actions.get("count") or 0) > 0:
            available.append((action_score, 0.6))
        total_weight = sum(weight for _, weight in available)
        combined = round(
            (
                sum(score * weight for score, weight in available)
                / total_weight
            )
            if total_weight
            else 0.0,
            2,
        )
        effective_weights = {
            "news": (
                round(0.4 / total_weight, 4)
                if total_weight
                and int(news.get("count") or 0) > 0
                else 0.0
            ),
            "corporate_actions": (
                round(0.6 / total_weight, 4)
                if total_weight
                and int(actions.get("count") or 0) > 0
                else 0.0
            ),
        }

        return {
            "status": "ready",
            "symbol": normalized,
            "combined_intelligence_score": combined,
            "score_range": [-10, 10],
            "score_weights": {
                "news": 0.4,
                "corporate_actions": 0.6,
            },
            "effective_score_weights": effective_weights,
            "news": {
                key: news.get(key)
                for key in (
                    "count",
                    "positive",
                    "negative",
                    "neutral",
                    "breaking",
                    "average_impact_score",
                    "latest_fetch_at",
                    "methodology",
                )
            },
            "corporate_actions": {
                key: actions.get(key)
                for key in (
                    "count",
                    "positive_impact",
                    "negative_impact",
                    "high_impact",
                    "upcoming",
                    "next_event_at",
                    "average_impact_score",
                    "latest_fetch_at",
                    "methodology",
                )
            },
            "interpretation": (
                "heuristic_evidence_summary_not_trade_signal"
            ),
        }

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()


__all__ = ["IntelligenceDashboardService"]
