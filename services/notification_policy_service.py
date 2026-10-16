"""Alert policy and routing preferences for canonical notifications."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from database.repositories.notification_policy_repository import (
    NotificationPolicyRepository,
)


class NotificationPolicyService:
    VERSION = "R68.9"
    MARKET_TZ = ZoneInfo("Asia/Kolkata")
    SEVERITY_ORDER = {
        "INFO": 10,
        "SUCCESS": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }
    CATEGORIES = (
        "scanner",
        "paper",
        "risk",
        "system",
        "intelligence",
        "market",
        "portfolio",
    )
    DEFAULT_POLICY = {
        "version": VERSION,
        "delivery_enabled": True,
        "categories": {
            "scanner": {
                "enabled": True,
                "minimum_severity": "INFO",
            },
            "paper": {
                "enabled": True,
                "minimum_severity": "INFO",
            },
            "risk": {
                "enabled": True,
                "minimum_severity": "WARNING",
            },
            "system": {
                "enabled": True,
                "minimum_severity": "WARNING",
            },
            "intelligence": {
                "enabled": True,
                "minimum_severity": "WARNING",
            },
            "market": {
                "enabled": True,
                "minimum_severity": "WARNING",
            },
            "portfolio": {
                "enabled": True,
                "minimum_severity": "WARNING",
            },
        },
        "quiet_hours": {
            "enabled": False,
            "start": "22:00",
            "end": "07:00",
            "timezone": "Asia/Kolkata",
            "allow_critical": True,
        },
        "daily_summary": {
            "enabled": False,
            "time_ist": "18:30",
            "skip_empty": True,
            "notable_limit": 10,
        },
    }

    def __init__(
        self,
        repository: NotificationPolicyRepository | None = None,
    ) -> None:
        self._owns_repository = repository is None
        self.repository = repository or NotificationPolicyRepository()

    @staticmethod
    def _clock(value: Any, *, field: str) -> str:
        text = str(value or "").strip()
        try:
            parsed = datetime.strptime(text, "%H:%M")
        except ValueError as exc:
            raise ValueError(
                f"{field} must use 24-hour HH:MM format"
            ) from exc
        return parsed.strftime("%H:%M")

    @classmethod
    def _severity(cls, value: Any) -> str:
        severity = str(value or "").strip().upper()
        if severity not in cls.SEVERITY_ORDER:
            raise ValueError(
                "minimum_severity must be one of: "
                + ", ".join(cls.SEVERITY_ORDER)
            )
        return severity

    @classmethod
    def _normalized_category_policy(
        cls,
        category: str,
        value: Any,
    ) -> dict[str, Any]:
        if category not in cls.CATEGORIES:
            raise ValueError(f"unsupported category: {category}")
        raw = value if isinstance(value, dict) else {}
        return {
            "enabled": bool(raw.get("enabled", True)),
            "minimum_severity": cls._severity(
                raw.get("minimum_severity", "INFO")
            ),
        }

    @classmethod
    def normalize(
        cls,
        policy: dict[str, Any] | None,
    ) -> dict[str, Any]:
        raw = policy if isinstance(policy, dict) else {}
        defaults = deepcopy(cls.DEFAULT_POLICY)

        raw_categories = raw.get("categories")
        raw_categories = (
            raw_categories
            if isinstance(raw_categories, dict)
            else {}
        )
        categories: dict[str, Any] = {}
        for category in cls.CATEGORIES:
            merged = {
                **defaults["categories"][category],
                **(
                    raw_categories.get(category)
                    if isinstance(
                        raw_categories.get(category),
                        dict,
                    )
                    else {}
                ),
            }
            categories[category] = (
                cls._normalized_category_policy(
                    category,
                    merged,
                )
            )

        raw_quiet = raw.get("quiet_hours")
        raw_quiet = (
            raw_quiet
            if isinstance(raw_quiet, dict)
            else {}
        )
        quiet = {
            **defaults["quiet_hours"],
            **raw_quiet,
        }
        quiet_hours = {
            "enabled": bool(quiet.get("enabled", False)),
            "start": cls._clock(
                quiet.get("start"),
                field="quiet_hours.start",
            ),
            "end": cls._clock(
                quiet.get("end"),
                field="quiet_hours.end",
            ),
            "timezone": "Asia/Kolkata",
            "allow_critical": bool(
                quiet.get("allow_critical", True)
            ),
        }

        raw_summary = raw.get("daily_summary")
        raw_summary = (
            raw_summary
            if isinstance(raw_summary, dict)
            else {}
        )
        summary = {
            **defaults["daily_summary"],
            **raw_summary,
        }
        try:
            notable_limit = int(
                summary.get("notable_limit", 10)
            )
        except (TypeError, ValueError):
            notable_limit = 10
        daily_summary = {
            "enabled": bool(summary.get("enabled", False)),
            "time_ist": cls._clock(
                summary.get("time_ist"),
                field="daily_summary.time_ist",
            ),
            "skip_empty": bool(
                summary.get("skip_empty", True)
            ),
            "notable_limit": max(
                1,
                min(notable_limit, 25),
            ),
        }

        return {
            "version": cls.VERSION,
            "delivery_enabled": bool(
                raw.get(
                    "delivery_enabled",
                    defaults["delivery_enabled"],
                )
            ),
            "categories": categories,
            "quiet_hours": quiet_hours,
            "daily_summary": daily_summary,
        }

    def current(self) -> dict[str, Any]:
        stored = self.repository.get()
        if stored is None:
            return {
                "status": "default",
                "source": "built_in_default",
                "updated_at": None,
                "policy": self.normalize(None),
            }
        return {
            "status": "configured",
            "source": "sqlite_settings",
            "updated_at": stored.get("updated_at"),
            "policy": self.normalize(
                stored.get("policy")
            ),
        }

    def update(
        self,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = self.normalize(policy)
        stored = self.repository.set(normalized)
        return {
            "status": "updated",
            "source": "sqlite_settings",
            "updated_at": stored.get("updated_at"),
            "policy": normalized,
        }

    def reset(self) -> dict[str, Any]:
        removed = self.repository.reset()
        return {
            "status": "reset",
            "removed": bool(removed),
            "source": "built_in_default",
            "updated_at": None,
            "policy": self.normalize(None),
        }

    @staticmethod
    def _parse_time(value: str) -> time:
        return datetime.strptime(
            value,
            "%H:%M",
        ).time()

    @classmethod
    def _in_quiet_hours(
        cls,
        now: datetime,
        quiet: dict[str, Any],
    ) -> bool:
        if not quiet.get("enabled"):
            return False
        local = (
            now.astimezone(cls.MARKET_TZ)
            if now.tzinfo
            else now.replace(tzinfo=cls.MARKET_TZ)
        )
        current = local.time().replace(
            second=0,
            microsecond=0,
        )
        start = cls._parse_time(str(quiet["start"]))
        end = cls._parse_time(str(quiet["end"]))
        if start == end:
            return True
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def evaluate(
        self,
        *,
        category: str,
        severity: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = self.current()["policy"]
        normalized_category = str(
            category or ""
        ).strip().lower()
        normalized_severity = str(
            severity or "INFO"
        ).strip().upper()

        if normalized_category not in self.CATEGORIES:
            raise ValueError(
                "category must be one of: "
                + ", ".join(self.CATEGORIES)
            )
        if normalized_severity not in self.SEVERITY_ORDER:
            raise ValueError(
                "severity must be one of: "
                + ", ".join(self.SEVERITY_ORDER)
            )

        if not current["delivery_enabled"]:
            return {
                "allowed": False,
                "reason": "delivery_disabled",
                "policy": current,
            }

        category_policy = current["categories"][
            normalized_category
        ]
        if not category_policy["enabled"]:
            return {
                "allowed": False,
                "reason": "category_disabled",
                "policy": current,
            }

        minimum = category_policy["minimum_severity"]
        if (
            self.SEVERITY_ORDER[normalized_severity]
            < self.SEVERITY_ORDER[minimum]
        ):
            return {
                "allowed": False,
                "reason": (
                    "severity_below_minimum:"
                    + minimum
                ),
                "policy": current,
            }

        quiet = current["quiet_hours"]
        reference = now or datetime.now(self.MARKET_TZ)
        if self._in_quiet_hours(reference, quiet):
            if not (
                normalized_severity == "CRITICAL"
                and quiet["allow_critical"]
            ):
                return {
                    "allowed": False,
                    "reason": "quiet_hours",
                    "policy": current,
                }

        return {
            "allowed": True,
            "reason": None,
            "policy": current,
        }

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()


__all__ = ["NotificationPolicyService"]
