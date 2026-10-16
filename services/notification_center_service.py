"""Canonical Discord-only notification center and event router."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from typing import Any
from uuid import uuid4

from database.repositories.notification_event_repository import (
    NotificationEventRepository,
)
from services.discord_service import DiscordService


class NotificationEventNotFoundError(KeyError):
    pass


class NotificationCenterService:
    CHANNEL = "discord"
    CATEGORIES = (
        "scanner",
        "paper",
        "risk",
        "system",
        "intelligence",
        "market",
        "portfolio",
    )
    SEVERITIES = (
        "INFO",
        "SUCCESS",
        "WARNING",
        "ERROR",
        "CRITICAL",
    )
    STATUSES = (
        "recorded",
        "sent",
        "failed",
        "blocked",
        "suppressed",
    )

    def __init__(
        self,
        *,
        discord: DiscordService,
        repository: NotificationEventRepository | None = None,
        cooldown_minutes: int | None = None,
    ) -> None:
        if discord is None:
            raise ValueError("discord transport is required")
        self.discord = discord
        self._owns_repository = repository is None
        self.repository = repository or NotificationEventRepository()
        self.cooldown_minutes = (
            self._env_int(
                "TRENDFORGE_ALERT_COOLDOWN_MINUTES",
                15,
                minimum=0,
                maximum=1440,
            )
            if cooldown_minutes is None
            else max(0, min(int(cooldown_minutes), 1440))
        )

    @staticmethod
    def _env_int(
        name: str,
        default: int,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        raw = os.getenv(name)
        try:
            value = int(raw) if raw is not None else int(default)
        except (TypeError, ValueError):
            value = int(default)
        return min(max(value, minimum), maximum)

    @classmethod
    def _category(cls, value: Any) -> str:
        category = str(value or "").strip().lower()
        if category not in cls.CATEGORIES:
            raise ValueError(
                "category must be one of: "
                + ", ".join(cls.CATEGORIES)
            )
        return category

    @classmethod
    def _severity(cls, value: Any) -> str:
        severity = str(value or "INFO").strip().upper()
        if severity not in cls.SEVERITIES:
            raise ValueError(
                "severity must be one of: "
                + ", ".join(cls.SEVERITIES)
            )
        return severity

    @staticmethod
    def _text(
        value: Any,
        *,
        field: str,
        maximum: int,
        required: bool = True,
    ) -> str:
        text = str(value or "").strip()
        if required and not text:
            raise ValueError(f"{field} is required")
        if len(text) > maximum:
            raise ValueError(
                f"{field} must be {maximum} characters or fewer"
            )
        return text

    @staticmethod
    def _symbol(value: Any) -> str | None:
        symbol = str(value or "").strip().upper()
        if not symbol:
            return None
        if len(symbol) > 30:
            raise ValueError(
                "symbol must be 30 characters or fewer"
            )
        return symbol

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _dedupe_key(
        *,
        category: str,
        event_type: str,
        symbol: str | None,
        title: str,
        message: str,
        supplied: str | None,
    ) -> str:
        if supplied:
            normalized = str(supplied).strip()
            if len(normalized) > 200:
                raise ValueError(
                    "dedupe_key must be 200 characters or fewer"
                )
            if normalized:
                return normalized

        raw = "|".join(
            (
                category,
                event_type,
                symbol or "",
                title,
                message,
            )
        )
        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()

    def readiness(self) -> dict[str, Any]:
        discord = self.discord.health()
        return {
            "status": (
                "ready"
                if discord.get("enabled")
                else "not_configured"
                if not discord.get("configured")
                else "disabled"
            ),
            "channel": self.CHANNEL,
            "discord": discord,
            "cooldown_minutes": self.cooldown_minutes,
            "categories": list(self.CATEGORIES),
            "severities": list(self.SEVERITIES),
            "persisted_events": self.repository.count(),
            "whatsapp_supported": False,
            "email_supported": False,
            "webhook_secret_exposed": False,
        }

    def route_event(
        self,
        *,
        event_type: str,
        category: str,
        severity: str = "INFO",
        title: str,
        message: str,
        symbol: str | None = None,
        source: str = "trendforge",
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        deliver: bool = True,
    ) -> dict[str, Any]:
        normalized_category = self._category(category)
        normalized_severity = self._severity(severity)
        normalized_type = self._text(
            event_type,
            field="event_type",
            maximum=80,
        ).lower()
        normalized_title = self._text(
            title,
            field="title",
            maximum=256,
        )
        normalized_message = self._text(
            message,
            field="message",
            maximum=4000,
        )
        normalized_source = self._text(
            source,
            field="source",
            maximum=100,
        )
        normalized_symbol = self._symbol(symbol)
        body = payload if isinstance(payload, dict) else {}

        resolved_dedupe = self._dedupe_key(
            category=normalized_category,
            event_type=normalized_type,
            symbol=normalized_symbol,
            title=normalized_title,
            message=normalized_message,
            supplied=dedupe_key,
        )

        now = self._now()
        if self.cooldown_minutes > 0:
            since = (
                now
                - timedelta(minutes=self.cooldown_minutes)
            ).isoformat()
            duplicate = self.repository.recent_dedupe(
                resolved_dedupe,
                since=since,
            )
        else:
            duplicate = None

        event_id = str(uuid4())
        base = {
            "event_id": event_id,
            "event_type": normalized_type,
            "category": normalized_category,
            "severity": normalized_severity,
            "symbol": normalized_symbol,
            "title": normalized_title,
            "message": normalized_message,
            "source": normalized_source,
            "channel": self.CHANNEL,
            "dedupe_key": resolved_dedupe,
            "payload": body,
            "created_at": now.isoformat(),
        }

        if duplicate is not None:
            return self.repository.create(
                {
                    **base,
                    "status": "suppressed",
                    "error": (
                        "cooldown_duplicate:"
                        + str(duplicate.get("event_id") or "")
                    ),
                    "payload": {
                        **body,
                        "duplicate_of": duplicate.get("event_id"),
                    },
                }
            )

        if not deliver:
            return self.repository.create(
                {
                    **base,
                    "status": "recorded",
                }
            )

        if not self.discord.configured:
            return self.repository.create(
                {
                    **base,
                    "status": "blocked",
                    "error": "discord_not_configured",
                }
            )

        event = self.repository.create(
            {
                **base,
                "status": "recorded",
            }
        )

        fields = [
            {
                "name": "Category",
                "value": normalized_category,
                "inline": True,
            },
            {
                "name": "Event",
                "value": normalized_type,
                "inline": True,
            },
            {
                "name": "Source",
                "value": normalized_source,
                "inline": True,
            },
        ]
        if normalized_symbol:
            fields.append(
                {
                    "name": "Symbol",
                    "value": normalized_symbol,
                    "inline": True,
                }
            )

        result = self.discord.send_notification(
            title=normalized_title,
            message=normalized_message,
            severity=normalized_severity,
            fields=fields,
            footer=f"TrendForge · {event_id}",
        )
        if result.get("ok"):
            updated = self.repository.update_delivery(
                event_id,
                status="sent",
                sent_at=self._now().isoformat(),
            )
        else:
            status = (
                "blocked"
                if result.get("status")
                in {"not_configured", "disabled"}
                else "failed"
            )
            updated = self.repository.update_delivery(
                event_id,
                status=status,
                error=str(
                    result.get("error")
                    or result.get("status")
                    or "discord_delivery_failed"
                ),
            )
        return updated or event

    def test_delivery(self) -> dict[str, Any]:
        return self.route_event(
            event_type="discord_test",
            category="system",
            severity="SUCCESS",
            title="TrendForge Discord Test",
            message=(
                "The canonical R68.7 notification route "
                "successfully reached Discord."
            ),
            source="notification_center",
            dedupe_key=f"discord-test:{uuid4()}",
            deliver=True,
        )

    def events(
        self,
        *,
        limit: int = 100,
        category: str | None = None,
        status: str | None = None,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        normalized_category = (
            self._category(category)
            if category
            else None
        )
        normalized_status = (
            str(status).strip().lower()
            if status
            else None
        )
        if (
            normalized_status
            and normalized_status not in self.STATUSES
        ):
            raise ValueError(
                "status must be one of: "
                + ", ".join(self.STATUSES)
            )
        normalized_symbol = (
            self._symbol(symbol)
            if symbol
            else None
        )
        rows = self.repository.latest(
            limit=limit,
            category=normalized_category,
            status=normalized_status,
            symbol=normalized_symbol,
        )
        return {
            "status": "ready",
            "returned": len(rows),
            "filters": {
                "category": normalized_category,
                "status": normalized_status,
                "symbol": normalized_symbol,
            },
            "events": rows,
        }

    def get(
        self,
        event_id: str,
    ) -> dict[str, Any]:
        normalized = self._text(
            event_id,
            field="event_id",
            maximum=120,
        )
        row = self.repository.get(normalized)
        if row is None:
            raise NotificationEventNotFoundError(
                normalized
            )
        return row

    def summary(self) -> dict[str, Any]:
        latest = self.repository.latest(limit=1)
        return {
            "status": "ready",
            "channel": self.CHANNEL,
            "total": self.repository.count(),
            "sent": self.repository.count(status="sent"),
            "recorded": self.repository.count(
                status="recorded"
            ),
            "failed": self.repository.count(status="failed"),
            "blocked": self.repository.count(status="blocked"),
            "suppressed": self.repository.count(
                status="suppressed"
            ),
            "categories": self.repository.category_counts(),
            "latest_event": latest[0] if latest else None,
        }

    def scanner_alert(self, **kwargs) -> dict[str, Any]:
        return self.route_event(
            category="scanner",
            source="scanner",
            **kwargs,
        )

    def paper_alert(self, **kwargs) -> dict[str, Any]:
        return self.route_event(
            category="paper",
            source="paper_trading",
            **kwargs,
        )

    def risk_alert(self, **kwargs) -> dict[str, Any]:
        return self.route_event(
            category="risk",
            source="risk_manager",
            **kwargs,
        )

    def system_alert(self, **kwargs) -> dict[str, Any]:
        return self.route_event(
            category="system",
            source="system",
            **kwargs,
        )

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()


__all__ = [
    "NotificationCenterService",
    "NotificationEventNotFoundError",
]
