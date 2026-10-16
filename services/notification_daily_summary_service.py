"""Daily Discord digest built from canonical notification evidence."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo


class NotificationDailySummaryService:
    MARKET_TZ = ZoneInfo("Asia/Kolkata")
    EVENT_TYPE = "daily_discord_summary"

    def __init__(
        self,
        *,
        center: Any,
        policy: Any,
    ) -> None:
        if center is None:
            raise ValueError("notification center is required")
        if policy is None:
            raise ValueError("notification policy service is required")
        self.center = center
        self.policy = policy

    @classmethod
    def _date(cls, value: str | date | None) -> date:
        if value is None:
            return datetime.now(cls.MARKET_TZ).date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value).strip())
        except ValueError as exc:
            raise ValueError(
                "summary date must use YYYY-MM-DD"
            ) from exc

    @classmethod
    def _window(
        cls,
        value: str | date | None,
    ) -> tuple[date, datetime, datetime]:
        target = cls._date(value)
        start_local = datetime.combine(
            target,
            time.min,
            tzinfo=cls.MARKET_TZ,
        )
        end_local = start_local + timedelta(days=1)
        return (
            target,
            start_local.astimezone(ZoneInfo("UTC")),
            end_local.astimezone(ZoneInfo("UTC")),
        )

    @staticmethod
    def _notable(row: dict[str, Any]) -> bool:
        severity = str(
            row.get("severity") or "INFO"
        ).upper()
        event_type = str(
            row.get("event_type") or ""
        ).lower()
        return (
            severity in {"CRITICAL", "ERROR", "WARNING"}
            or event_type
            in {
                "scanner_pick",
                "paper_position_opened",
                "paper_position_closed",
                "paper_entry_blocked",
                "paper_risk_block",
                "scanner_failed",
                "paper_monitor_failed",
            }
        )

    @staticmethod
    def _short(text: Any, maximum: int = 180) -> str:
        normalized = " ".join(
            str(text or "").split()
        )
        if len(normalized) <= maximum:
            return normalized
        return normalized[: maximum - 1].rstrip() + "…"

    def preview(
        self,
        *,
        summary_date: str | date | None = None,
    ) -> dict[str, Any]:
        target, start, end = self._window(summary_date)
        rows = self.center.repository.between(
            start=start.isoformat(),
            end=end.isoformat(),
            limit=5000,
        )
        rows = [
            row
            for row in rows
            if str(row.get("event_type") or "")
            != self.EVENT_TYPE
        ]

        statuses = Counter(
            str(row.get("status") or "unknown")
            for row in rows
        )
        categories = Counter(
            str(row.get("category") or "unknown")
            for row in rows
        )
        severities = Counter(
            str(row.get("severity") or "INFO").upper()
            for row in rows
        )
        event_types = Counter(
            str(row.get("event_type") or "unknown")
            for row in rows
        )

        configured = self.policy.current()["policy"][
            "daily_summary"
        ]
        notable_limit = int(
            configured.get("notable_limit") or 10
        )
        notable = [
            row for row in rows
            if self._notable(row)
        ][-notable_limit:]
        notable.reverse()

        scanner_picks = event_types.get("scanner_pick", 0)
        paper_opened = event_types.get(
            "paper_position_opened",
            0,
        )
        paper_closed = event_types.get(
            "paper_position_closed",
            0,
        )
        risk_events = categories.get("risk", 0)
        delivery_issues = (
            statuses.get("failed", 0)
            + statuses.get("blocked", 0)
        )

        return {
            "status": "ready",
            "date": target.isoformat(),
            "timezone": "Asia/Kolkata",
            "window": {
                "start_utc": start.isoformat(),
                "end_utc": end.isoformat(),
            },
            "event_count": len(rows),
            "statuses": dict(sorted(statuses.items())),
            "categories": dict(sorted(categories.items())),
            "severities": dict(sorted(severities.items())),
            "event_types": dict(
                sorted(event_types.items())
            ),
            "scanner_picks": scanner_picks,
            "paper_opened": paper_opened,
            "paper_closed": paper_closed,
            "risk_events": risk_events,
            "delivery_issues": delivery_issues,
            "notable_events": notable,
            "policy": dict(configured),
        }

    def _message(
        self,
        preview: dict[str, Any],
    ) -> str:
        statuses = preview["statuses"]
        categories = preview["categories"]
        lines = [
            f"TrendForge daily alert summary · {preview['date']}",
            (
                f"Events {preview['event_count']} · "
                f"Sent {statuses.get('sent', 0)} · "
                f"Filtered {statuses.get('filtered', 0)} · "
                f"Suppressed {statuses.get('suppressed', 0)} · "
                f"Issues {preview['delivery_issues']}"
            ),
            (
                f"Scanner picks {preview['scanner_picks']} · "
                f"Paper opened {preview['paper_opened']} · "
                f"Paper closed {preview['paper_closed']} · "
                f"Risk events {preview['risk_events']}"
            ),
        ]

        active_categories = [
            f"{name}:{count}"
            for name, count in sorted(
                categories.items(),
                key=lambda item: (
                    -item[1],
                    item[0],
                ),
            )
            if count
        ]
        if active_categories:
            lines.append(
                "Categories · "
                + " · ".join(active_categories)
            )

        notable = preview["notable_events"]
        if notable:
            lines.append("Notable:")
            for row in notable:
                symbol = str(
                    row.get("symbol") or ""
                ).strip().upper()
                prefix = (
                    f"{symbol} · "
                    if symbol
                    else ""
                )
                lines.append(
                    "- "
                    + prefix
                    + self._short(
                        row.get("title")
                        or row.get("message")
                        or row.get("event_type")
                    )
                )
        else:
            lines.append("Notable: none")

        message = "\n".join(lines)
        return message[:4000]

    def already_sent(
        self,
        summary_date: str | date | None = None,
    ) -> dict[str, Any] | None:
        target = self._date(summary_date)
        return self.center.repository.find_dedupe(
            f"daily-summary:{target.isoformat()}",
            statuses=("sent", "recorded"),
        )

    def send(
        self,
        *,
        summary_date: str | date | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        preview = self.preview(
            summary_date=summary_date
        )
        full_policy = self.policy.current()["policy"]
        policy = preview["policy"]
        target = preview["date"]

        if not full_policy.get("delivery_enabled", True):
            return {
                "status": "delivery_disabled",
                "date": target,
                "preview": preview,
            }

        if not policy.get("enabled"):
            return {
                "status": "disabled",
                "date": target,
                "preview": preview,
            }

        existing = self.already_sent(target)
        if existing is not None and not force:
            return {
                "status": "already_sent",
                "date": target,
                "event": existing,
                "preview": preview,
            }

        if (
            not preview["event_count"]
            and policy.get("skip_empty", True)
        ):
            return {
                "status": "skipped_empty",
                "date": target,
                "preview": preview,
            }

        severity = (
            "WARNING"
            if preview["delivery_issues"]
            else "INFO"
        )
        dedupe_key = (
            f"daily-summary:{target}"
            if not force
            else f"daily-summary:{target}:force:{uuid4()}"
        )
        event = self.center.route_event(
            event_type=self.EVENT_TYPE,
            category="system",
            severity=severity,
            title=f"TrendForge Daily Summary · {target}",
            message=self._message(preview),
            source="notification_daily_summary",
            payload={
                "summary_date": target,
                "event_count": preview["event_count"],
                "statuses": preview["statuses"],
                "categories": preview["categories"],
                "severities": preview["severities"],
                "scanner_picks": preview["scanner_picks"],
                "paper_opened": preview["paper_opened"],
                "paper_closed": preview["paper_closed"],
                "risk_events": preview["risk_events"],
                "delivery_issues": preview["delivery_issues"],
                "notable_event_ids": [
                    row.get("event_id")
                    for row in preview["notable_events"]
                    if row.get("event_id")
                ],
            },
            dedupe_key=dedupe_key,
            deliver=True,
            policy_bypass=True,
        )
        return {
            "status": str(
                event.get("status") or "unknown"
            ),
            "date": target,
            "event": event,
            "preview": preview,
        }


__all__ = ["NotificationDailySummaryService"]
