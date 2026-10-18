"""Production operations audit, missed-run alerts and reliability metrics."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from database.repositories.market_day_operations_repository import (
    MarketDayOperationsRepository,
)


class OperationsReliabilityService:
    VERSION = "R70.1"
    MARKET_TZ = ZoneInfo("Asia/Kolkata")
    OPERATIONS = ("morning", "eod")
    POST_WINDOW_AUDIT_GRACE_MINUTES = 10

    FAILURE_STATES = {
        "missed",
        "degraded",
        "configuration_error",
    }

    def __init__(
        self,
        *,
        operations_service: Any,
        repository: MarketDayOperationsRepository | None = None,
        notification_center: Any | None = None,
    ) -> None:
        self.operations_service = operations_service
        self._owns_repository = repository is None
        self.repository = (
            repository
            or getattr(operations_service, "repository", None)
            or MarketDayOperationsRepository()
        )
        self.notification_center = notification_center

    @classmethod
    def _local_now(
        cls,
        value: datetime | None = None,
    ) -> datetime:
        current = value or datetime.now(cls.MARKET_TZ)
        if current.tzinfo is None:
            return current.replace(tzinfo=cls.MARKET_TZ)
        return current.astimezone(cls.MARKET_TZ)

    @staticmethod
    def _parse(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=OperationsReliabilityService.MARKET_TZ
            )
        return parsed.astimezone(
            OperationsReliabilityService.MARKET_TZ
        )

    @classmethod
    def _audit_status(
        cls,
        contract: dict[str, Any],
        *,
        strict: bool,
    ) -> str:
        status = str(contract.get("status") or "")
        reason = str(contract.get("reason") or "")

        if status == "satisfied":
            return "healthy"
        if status == "degraded":
            return "degraded"
        if status == "missed_window":
            return "missed"
        if status == "not_required":
            if reason == "non_market_day":
                return "not_required"
            if strict and reason in {
                "automation_disabled",
                "operation_disabled",
            }:
                return "configuration_error"
            return "disabled"
        if status in {"pending", "due"}:
            return status
        return "unknown"

    @classmethod
    def _completion_delay_minutes(
        cls,
        contract: dict[str, Any],
    ) -> float | None:
        run = contract.get("successful_run")
        if not isinstance(run, dict):
            return None
        completed = cls._parse(
            run.get("completed_at_ist")
        )
        window_start = cls._parse(
            contract.get("window_start_ist")
        )
        if completed is None or window_start is None:
            return None
        return round(
            (completed - window_start).total_seconds()
            / 60.0,
            2,
        )

    def _alert(
        self,
        *,
        operation: str,
        contract: dict[str, Any],
        audit_status: str,
        trigger_source: str,
    ) -> dict[str, Any] | None:
        if (
            audit_status not in self.FAILURE_STATES
            or self.notification_center is None
        ):
            return None

        date_ist = str(
            contract.get("date_ist") or ""
        )
        audit_event_key = (
            f"post-window:{date_ist}:"
            f"{operation}:{audit_status}"
        )
        previous = self.repository.audit_event(
            audit_event_key
        )
        previous_alert = (
            previous.get("alert")
            if isinstance(previous, dict)
            else None
        )
        if (
            isinstance(previous_alert, dict)
            and previous_alert.get("status")
            in {"sent", "filtered", "suppressed"}
        ):
            return {
                "status": "already_alerted",
                "event_id": previous_alert.get("event_id"),
            }

        route = getattr(
            self.notification_center,
            "route_event",
            None,
        )
        if not callable(route):
            return None

        if audit_status == "missed":
            severity = "CRITICAL"
            title = (
                f"TrendForge {operation.title()} Run Missed"
            )
            message = (
                f"{operation.title()} operation has no successful "
                f"run after its {contract.get('window_end_ist')} "
                "IST execution window."
            )
        elif audit_status == "degraded":
            severity = "ERROR"
            title = (
                f"TrendForge {operation.title()} Run Degraded"
            )
            message = (
                f"{operation.title()} operation recorded a degraded "
                f"run for {date_ist}. Review failed operation steps."
            )
        else:
            severity = "ERROR"
            title = (
                f"TrendForge {operation.title()} Automation Drift"
            )
            message = (
                f"{operation.title()} production scheduling is "
                f"unexpectedly disabled for {date_ist}: "
                f"{contract.get('reason')}."
            )

        try:
            return route(
                event_type="operations_reliability_alert",
                category="system",
                severity=severity,
                title=title,
                message=message,
                source="operations_reliability",
                payload={
                    "version": self.VERSION,
                    "operation": operation,
                    "date_ist": date_ist,
                    "audit_status": audit_status,
                    "contract_status": contract.get("status"),
                    "reason": contract.get("reason"),
                    "trigger_source": trigger_source,
                    "window_start_ist": contract.get(
                        "window_start_ist"
                    ),
                    "window_end_ist": contract.get(
                        "window_end_ist"
                    ),
                    "broker_orders_allowed": False,
                },
                dedupe_key=(
                    f"operations-reliability:{date_ist}:"
                    f"{operation}:{audit_status}"
                ),
                deliver=True,
            )
        except Exception as exc:
            return {
                "status": "failed",
                "error": (
                    f"notification_side_channel:"
                    f"{type(exc).__name__}: {exc}"
                ),
            }

    def record_external_tick(
        self,
        *,
        operation: str,
        before: dict[str, Any],
        tick: dict[str, Any],
        after: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = self._local_now(now)
        event = {
            "audit_id": str(uuid4()),
            "event_type": "external_tick",
            "event_key": (
                f"external-tick:{operation}:"
                f"{current.isoformat()}"
            ),
            "version": self.VERSION,
            "recorded_at_ist": current.isoformat(),
            "date_ist": str(
                after.get("date_ist")
                or current.date().isoformat()
            ),
            "operation": operation,
            "trigger_source": "external_scheduler",
            "audit_status": self._audit_status(
                after,
                strict=True,
            ),
            "contract_status": after.get("status"),
            "reason": after.get("reason"),
            "before_status": before.get("status"),
            "tick_status": tick.get("status"),
            "after_status": after.get("status"),
            "completion_delay_minutes": (
                self._completion_delay_minutes(after)
            ),
            "broker_orders_allowed": False,
        }
        return self.repository.record_audit_event(event)

    def audit(
        self,
        operation: str,
        *,
        now: datetime | None = None,
        trigger_source: str = "manual",
        strict: bool = False,
        deliver_alerts: bool = True,
    ) -> dict[str, Any]:
        normalized = str(operation or "").strip().lower()
        if normalized not in self.OPERATIONS:
            raise ValueError(
                "operation must be morning or eod"
            )

        current = self._local_now(now)
        contract = self.operations_service.external_contract(
            normalized,
            now=current,
        )
        audit_status = self._audit_status(
            contract,
            strict=strict,
        )
        alert = (
            self._alert(
                operation=normalized,
                contract=contract,
                audit_status=audit_status,
                trigger_source=trigger_source,
            )
            if deliver_alerts
            else None
        )

        event = {
            "audit_id": str(uuid4()),
            "event_type": "post_window_audit",
            "event_key": (
                f"post-window:{contract.get('date_ist')}:"
                f"{normalized}:{audit_status}"
            ),
            "version": self.VERSION,
            "recorded_at_ist": current.isoformat(),
            "date_ist": contract.get("date_ist"),
            "operation": normalized,
            "trigger_source": trigger_source,
            "audit_status": audit_status,
            "contract_status": contract.get("status"),
            "reason": contract.get("reason"),
            "market_day": contract.get("market_day"),
            "market_phase": contract.get("market_phase"),
            "window_start_ist": contract.get(
                "window_start_ist"
            ),
            "window_end_ist": contract.get(
                "window_end_ist"
            ),
            "completion_delay_minutes": (
                self._completion_delay_minutes(contract)
            ),
            "successful_run": contract.get(
                "successful_run"
            ),
            "alert": (
                {
                    "status": alert.get("status"),
                    "event_id": alert.get("event_id"),
                    "error": alert.get("error"),
                }
                if isinstance(alert, dict)
                else None
            ),
            "broker_orders_allowed": False,
        }
        self.repository.record_audit_event(event)
        return {
            "status": audit_status,
            "operation": normalized,
            "contract": contract,
            "audit": event,
            "alert": alert,
            "broker_orders_allowed": False,
        }

    def audit_all(
        self,
        *,
        now: datetime | None = None,
        trigger_source: str = "manual",
        strict: bool = False,
        deliver_alerts: bool = True,
    ) -> dict[str, Any]:
        results = {
            operation: self.audit(
                operation,
                now=now,
                trigger_source=trigger_source,
                strict=strict,
                deliver_alerts=deliver_alerts,
            )
            for operation in self.OPERATIONS
        }
        failures = [
            operation
            for operation, result in results.items()
            if result.get("status")
            in self.FAILURE_STATES
        ]
        return {
            "status": (
                "degraded"
                if failures
                else "ready"
            ),
            "version": self.VERSION,
            "failures": failures,
            "results": results,
            "broker_orders_allowed": False,
        }

    def history(
        self,
        *,
        limit: int = 100,
        operation: str | None = None,
    ) -> dict[str, Any]:
        if operation is not None:
            normalized = str(operation).strip().lower()
            if normalized not in self.OPERATIONS:
                raise ValueError(
                    "operation must be morning or eod"
                )
        else:
            normalized = None

        rows = self.repository.audit_events(
            limit=limit,
            operation=normalized,
        )
        return {
            "status": "ready",
            "returned": len(rows),
            "operation": normalized,
            "events": rows,
        }

    @classmethod
    def _within_days(
        cls,
        row: dict[str, Any],
        *,
        cutoff: datetime,
    ) -> bool:
        recorded = cls._parse(
            row.get("recorded_at_ist")
        )
        return (
            recorded is not None
            and recorded >= cutoff
        )

    def reliability(
        self,
        *,
        days: int = 30,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = self._local_now(now)
        window_days = max(1, min(int(days), 90))
        cutoff = current - timedelta(days=window_days)
        rows = [
            row
            for row in self.repository.audit_events(
                limit=self.repository.MAX_AUDIT_EVENTS
            )
            if self._within_days(
                row,
                cutoff=cutoff,
            )
        ]

        per_operation: dict[str, dict[str, Any]] = {}
        latest: dict[str, dict[str, Any] | None] = {}
        all_delays: list[float] = []

        for operation in self.OPERATIONS:
            op_rows = [
                row
                for row in rows
                if row.get("operation") == operation
            ]
            audit_rows = [
                row
                for row in op_rows
                if row.get("event_type")
                == "post_window_audit"
            ]
            tick_rows = [
                row
                for row in op_rows
                if row.get("event_type")
                == "external_tick"
            ]

            counts: dict[str, int] = {}
            for row in audit_rows:
                state = str(
                    row.get("audit_status") or "unknown"
                )
                counts[state] = counts.get(state, 0) + 1

            success = counts.get("healthy", 0)
            failures = sum(
                counts.get(state, 0)
                for state in self.FAILURE_STATES
            )
            measured = success + failures
            reliability_pct = (
                round(success / measured * 100.0, 2)
                if measured
                else None
            )

            delays = [
                float(row["completion_delay_minutes"])
                for row in audit_rows
                if isinstance(
                    row.get("completion_delay_minutes"),
                    (int, float),
                )
            ]
            all_delays.extend(delays)
            latest_row = (
                audit_rows[0]
                if audit_rows
                else None
            )
            latest[operation] = latest_row

            per_operation[operation] = {
                "audit_checks": len(audit_rows),
                "external_ticks": len(tick_rows),
                "healthy": success,
                "missed": counts.get("missed", 0),
                "degraded": counts.get("degraded", 0),
                "configuration_errors": counts.get(
                    "configuration_error",
                    0,
                ),
                "not_required": counts.get(
                    "not_required",
                    0,
                ),
                "disabled": counts.get("disabled", 0),
                "pending": counts.get("pending", 0),
                "due": counts.get("due", 0),
                "reliability_pct": reliability_pct,
                "average_completion_delay_minutes": (
                    round(
                        sum(delays) / len(delays),
                        2,
                    )
                    if delays
                    else None
                ),
                "latest": latest_row,
            }

        current_contracts: dict[str, dict[str, Any]] = {}
        verification_gaps: list[str] = []
        live_failure = False

        for operation in self.OPERATIONS:
            try:
                contract = self.operations_service.external_contract(
                    operation,
                    now=current,
                )
            except Exception as exc:
                contract = {
                    "status": "unavailable",
                    "reason": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                    "operation": operation,
                }

            current_contracts[operation] = contract
            contract_status = str(
                contract.get("status") or ""
            )
            contract_reason = str(
                contract.get("reason") or ""
            )
            if contract_status in {
                "missed_window",
                "degraded",
            }:
                live_failure = True
            if (
                contract_status == "not_required"
                and contract_reason
                in {
                    "automation_disabled",
                    "operation_disabled",
                }
                and bool(contract.get("market_day"))
            ):
                live_failure = True

            window_end = self._parse(
                contract.get("window_end_ist")
            )
            audit_due = (
                window_end
                + timedelta(
                    minutes=self.POST_WINDOW_AUDIT_GRACE_MINUTES
                )
                if window_end is not None
                else None
            )
            if (
                bool(contract.get("market_day"))
                and bool(
                    contract.get("automation_enabled")
                )
                and bool(
                    contract.get("operation_enabled")
                )
                and audit_due is not None
                and current > audit_due
            ):
                verified_today = any(
                    row.get("event_type")
                    == "post_window_audit"
                    and row.get("operation") == operation
                    and row.get("date_ist")
                    == current.date().isoformat()
                    for row in rows
                )
                if not verified_today:
                    verification_gaps.append(operation)

        latest_states = [
            str(row.get("audit_status"))
            for row in latest.values()
            if isinstance(row, dict)
        ]
        if (
            live_failure
            or verification_gaps
            or any(
                state in self.FAILURE_STATES
                for state in latest_states
            )
        ):
            health = "RED"
        elif any(
            state in {"pending", "due", "unknown"}
            for state in latest_states
        ):
            health = "AMBER"
        elif latest_states:
            health = "GREEN"
        else:
            health = "NO_DATA"

        total_healthy = sum(
            value["healthy"]
            for value in per_operation.values()
        )
        total_failures = sum(
            value["missed"]
            + value["degraded"]
            + value["configuration_errors"]
            for value in per_operation.values()
        )
        measured = total_healthy + total_failures

        return {
            "status": "ready",
            "version": self.VERSION,
            "health": health,
            "window_days": window_days,
            "window_start_ist": cutoff.isoformat(),
            "now_ist": current.isoformat(),
            "total_audit_events": len(rows),
            "measured_operations": measured,
            "healthy_operations": total_healthy,
            "failed_operations": total_failures,
            "reliability_pct": (
                round(
                    total_healthy / measured * 100.0,
                    2,
                )
                if measured
                else None
            ),
            "average_completion_delay_minutes": (
                round(
                    sum(all_delays)
                    / len(all_delays),
                    2,
                )
                if all_delays
                else None
            ),
            "per_operation": per_operation,
            "latest": latest,
            "current_contracts": current_contracts,
            "verification_gaps": verification_gaps,
            "post_window_audit_grace_minutes": (
                self.POST_WINDOW_AUDIT_GRACE_MINUTES
            ),
            "safety": {
                "broker_orders_allowed": False,
                "scanner_execution_changed": False,
            },
        }

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()


__all__ = ["OperationsReliabilityService"]
