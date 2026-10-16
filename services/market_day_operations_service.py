"""Safe morning/EOD operational orchestration for TrendForge."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import threading
from typing import Any
from uuid import uuid4

from database.repositories.market_day_operations_repository import (
    MarketDayOperationsRepository,
)
from services.market_day_service import MarketDayService


class MarketDayOperationsService:
    VERSION = "R69.0"
    OPERATIONS = ("morning", "eod")
    DEFAULT_POLICY = {
        "version": VERSION,
        "automation_enabled": False,
        "market_day_only": True,
        "calendar": {
            "holiday_dates": [],
            "special_trading_dates": [],
        },
        "market_context_limit": 100,
        "morning": {
            "enabled": True,
            "time_ist": "08:45",
            "grace_minutes": 30,
            "refresh_market_context": True,
            "notify_discord": True,
        },
        "eod": {
            "enabled": True,
            "time_ist": "15:45",
            "grace_minutes": 30,
            "paper_safety_tick": True,
            "refresh_market_context": True,
            "portfolio_sync": False,
            "notify_discord": True,
        },
    }

    def __init__(
        self,
        *,
        repository: MarketDayOperationsRepository | None = None,
        market_context: Any | None = None,
        paper_monitor: Any | None = None,
        portfolio: Any | None = None,
        notification_center: Any | None = None,
    ) -> None:
        self._owns_repository = repository is None
        self.repository = repository or MarketDayOperationsRepository()
        self.market_context = market_context
        self.paper_monitor = paper_monitor
        self.portfolio = portfolio
        self.notification_center = notification_center
        self.calendar = MarketDayService()
        self._run_lock = threading.Lock()

    @staticmethod
    def _clock(value: Any, *, field: str) -> str:
        text = str(value or "").strip()
        try:
            parsed = datetime.strptime(text, "%H:%M")
        except ValueError as exc:
            raise ValueError(
                f"{field} must use 24-hour HH:MM"
            ) from exc
        return parsed.strftime("%H:%M")

    @staticmethod
    def _date_list(
        values: Any,
        *,
        field: str,
    ) -> list[str]:
        if values in (None, ""):
            return []
        if not isinstance(values, (list, tuple, set)):
            raise ValueError(
                f"{field} must be a list of YYYY-MM-DD dates"
            )
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            try:
                datetime.strptime(text, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(
                    f"{field} contains invalid date: {value}"
                ) from exc
            if text not in result:
                result.append(text)
        return sorted(result)

    @classmethod
    def normalize_policy(
        cls,
        policy: dict[str, Any] | None,
    ) -> dict[str, Any]:
        raw = policy if isinstance(policy, dict) else {}
        defaults = deepcopy(cls.DEFAULT_POLICY)

        raw_calendar = raw.get("calendar")
        raw_calendar = (
            raw_calendar
            if isinstance(raw_calendar, dict)
            else {}
        )
        calendar = {
            "holiday_dates": cls._date_list(
                raw_calendar.get(
                    "holiday_dates",
                    defaults["calendar"]["holiday_dates"],
                ),
                field="calendar.holiday_dates",
            ),
            "special_trading_dates": cls._date_list(
                raw_calendar.get(
                    "special_trading_dates",
                    defaults["calendar"][
                        "special_trading_dates"
                    ],
                ),
                field="calendar.special_trading_dates",
            ),
        }
        overlap = set(calendar["holiday_dates"]) & set(
            calendar["special_trading_dates"]
        )
        if overlap:
            raise ValueError(
                "calendar date cannot be both holiday and special trading day: "
                + ", ".join(sorted(overlap))
            )

        def operation_policy(
            name: str,
        ) -> dict[str, Any]:
            configured = raw.get(name)
            configured = (
                configured
                if isinstance(configured, dict)
                else {}
            )
            merged = {
                **defaults[name],
                **configured,
            }
            try:
                grace = int(merged.get("grace_minutes", 30))
            except (TypeError, ValueError):
                grace = 30
            if grace < 5 or grace > 180:
                raise ValueError(
                    f"{name}.grace_minutes must be between 5 and 180"
                )
            result = {
                "enabled": bool(merged.get("enabled", True)),
                "time_ist": cls._clock(
                    merged.get("time_ist"),
                    field=f"{name}.time_ist",
                ),
                "grace_minutes": grace,
                "refresh_market_context": bool(
                    merged.get("refresh_market_context", True)
                ),
                "notify_discord": bool(
                    merged.get("notify_discord", True)
                ),
            }
            if name == "eod":
                result["paper_safety_tick"] = bool(
                    merged.get("paper_safety_tick", True)
                )
                result["portfolio_sync"] = bool(
                    merged.get("portfolio_sync", False)
                )
            return result

        try:
            market_context_limit = int(
                raw.get(
                    "market_context_limit",
                    defaults["market_context_limit"],
                )
            )
        except (TypeError, ValueError):
            market_context_limit = defaults[
                "market_context_limit"
            ]
        if market_context_limit < 25 or market_context_limit > 500:
            raise ValueError(
                "market_context_limit must be between 25 and 500"
            )

        return {
            "version": cls.VERSION,
            "automation_enabled": bool(
                raw.get(
                    "automation_enabled",
                    defaults["automation_enabled"],
                )
            ),
            "market_day_only": bool(
                raw.get(
                    "market_day_only",
                    defaults["market_day_only"],
                )
            ),
            "calendar": calendar,
            "market_context_limit": market_context_limit,
            "morning": operation_policy("morning"),
            "eod": operation_policy("eod"),
        }

    def policy(self) -> dict[str, Any]:
        stored = self.repository.policy()
        if stored is None:
            return {
                "status": "default",
                "source": "built_in_default",
                "updated_at": None,
                "policy": self.normalize_policy(None),
            }
        return {
            "status": "configured",
            "source": "sqlite_settings",
            "updated_at": stored.get("updated_at"),
            "policy": self.normalize_policy(
                stored.get("policy")
            ),
        }

    def update_policy(
        self,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = self.normalize_policy(policy)
        stored = self.repository.set_policy(normalized)
        return {
            "status": "updated",
            "source": "sqlite_settings",
            "updated_at": stored.get("updated_at"),
            "policy": normalized,
        }

    def reset_policy(self) -> dict[str, Any]:
        removed = self.repository.reset_policy()
        return {
            "status": "reset",
            "removed": bool(removed),
            "source": "built_in_default",
            "updated_at": None,
            "policy": self.normalize_policy(None),
        }

    def session(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        policy = self.policy()["policy"]
        calendar = policy["calendar"]
        return self.calendar.session(
            now=now,
            holiday_dates=calendar["holiday_dates"],
            special_trading_dates=calendar[
                "special_trading_dates"
            ],
        )

    @staticmethod
    def _safe_health(service: Any) -> dict[str, Any]:
        if service is None:
            return {"status": "not_supported"}
        method = getattr(service, "health", None)
        if not callable(method):
            return {"status": "configured"}
        try:
            value = method()
            return (
                dict(value)
                if isinstance(value, dict)
                else {"status": "unknown"}
            )
        except Exception as exc:
            return {
                "status": "degraded",
                "error": f"{type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _safe_call(
        label: str,
        callback,
    ) -> dict[str, Any]:
        try:
            value = callback()
            return {
                "step": label,
                "status": "completed",
                "result": value,
            }
        except Exception as exc:
            return {
                "step": label,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _market_context_refresh(
        self,
        *,
        limit: int,
    ) -> dict[str, Any]:
        if self.market_context is None:
            raise RuntimeError(
                "Market context service is unavailable"
            )
        result = self.market_context.refresh(
            limit=limit,
            period="1y",
            interval="1d",
            refresh_universe=False,
        )
        breadth = result.get("breadth")
        breadth = breadth if isinstance(breadth, dict) else {}
        regime = result.get("regime")
        regime = regime if isinstance(regime, dict) else {}
        return {
            "status": result.get("status"),
            "requested_symbols": result.get(
                "requested_symbols"
            ),
            "analyzed_symbols": result.get(
                "analyzed_symbols"
            ),
            "coverage_pct": result.get("coverage_pct"),
            "breadth_direction": breadth.get("direction"),
            "breadth_score": breadth.get("breadth_score"),
            "regime": regime.get("regime"),
            "regime_score": regime.get("score"),
        }

    def _paper_safety_tick(
        self,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        if self.paper_monitor is None:
            raise RuntimeError(
                "Paper quote monitor is unavailable"
            )

        health = self._safe_health(
            self.paper_monitor
        )
        if health.get("running"):
            return {
                "status": "automatic_monitor_active",
                "direct_tick": False,
                "open_positions": health.get(
                    "open_position_count"
                ),
                "paper_only": True,
            }

        result = self.paper_monitor.tick(now=now)
        return {
            "status": result.get("status"),
            "direct_tick": True,
            "symbols": result.get("symbols") or [],
            "closed_count": len(
                result.get("closed") or []
            ),
            "closed": result.get("closed") or [],
            "open_positions": result.get(
                "open_positions"
            ),
            "total_pnl": result.get("total_pnl"),
            "paper_only": True,
        }

    def _portfolio_sync(self) -> dict[str, Any]:
        if self.portfolio is None:
            raise RuntimeError(
                "Portfolio service is unavailable"
            )
        result = self.portfolio.sync_portfolio()
        holdings = result.get("holdings")
        positions = result.get("positions")
        return {
            "status": result.get("status", "completed"),
            "scope": result.get("scope"),
            "count": result.get("count"),
            "holding_count": (
                len(holdings)
                if isinstance(holdings, list)
                else result.get("holding_count")
            ),
            "position_count": (
                len(positions)
                if isinstance(positions, list)
                else result.get("position_count")
            ),
            "portfolio_value": result.get("portfolio_value"),
            "investment": result.get("investment"),
            "total_pnl": result.get("total_pnl"),
        }

    def _daily_pnl(self) -> dict[str, Any]:
        if self.portfolio is None:
            return {"status": "not_supported"}
        method = getattr(
            self.portfolio,
            "pnl_statement",
            None,
        )
        if not callable(method):
            return {"status": "not_supported"}
        result = method(period="daily")
        summary = result.get("summary")
        summary = (
            summary
            if isinstance(summary, dict)
            else {}
        )
        return {
            "status": result.get("status", "ready"),
            "trade_count": summary.get("trade_count", 0),
            "net_pnl": summary.get("net_pnl", 0.0),
            "winning_trades": summary.get(
                "winning_trades",
                0,
            ),
            "losing_trades": summary.get(
                "losing_trades",
                0,
            ),
        }

    def _notify(
        self,
        *,
        operation: str,
        run: dict[str, Any],
        deliver: bool,
    ) -> dict[str, Any] | None:
        if self.notification_center is None:
            return None
        route = getattr(
            self.notification_center,
            "route_event",
            None,
        )
        if not callable(route):
            return None

        severity = (
            "WARNING"
            if run["status"] == "degraded"
            else "INFO"
        )
        failed_steps = [
            step["step"]
            for step in run["steps"]
            if step.get("status") == "failed"
        ]
        message = (
            f"{operation.title()} operations "
            f"{run['status']} for {run['date_ist']}. "
            f"Completed {run['completed_steps']} step(s); "
            f"failed {run['failed_steps']}."
        )
        if failed_steps:
            message += " Failed: " + ", ".join(failed_steps)

        try:
            return route(
                event_type=f"scheduled_{operation}_operations",
                category="system",
                severity=severity,
                title=(
                    "TrendForge Morning Operations"
                    if operation == "morning"
                    else "TrendForge End-of-Day Operations"
                ),
                message=message,
                source="market_day_operations",
                payload={
                    "operation": operation,
                    "run_id": run["run_id"],
                    "date_ist": run["date_ist"],
                    "status": run["status"],
                    "completed_steps": run["completed_steps"],
                    "failed_steps": failed_steps,
                    "paper_only": True,
                    "broker_orders_allowed": False,
                },
                dedupe_key=(
                    f"market-day-operations:{operation}:"
                    f"{run['date_ist']}"
                ),
                deliver=bool(deliver),
            )
        except Exception as exc:
            return {
                "status": "failed",
                "error": (
                    "notification_side_channel:"
                    f"{type(exc).__name__}: {exc}"
                ),
            }

    def run(
        self,
        operation: str,
        *,
        now: datetime | None = None,
        force: bool = False,
        scheduled: bool = False,
    ) -> dict[str, Any]:
        normalized = str(operation or "").strip().lower()
        if normalized not in self.OPERATIONS:
            raise ValueError(
                "operation must be morning or eod"
            )

        current = self.calendar.local_now(now)
        policy = self.policy()["policy"]
        operation_policy = policy[normalized]
        session = self.session(now=current)
        date_ist = session["date_ist"]

        if scheduled and not policy["automation_enabled"]:
            return {
                "status": "automation_disabled",
                "operation": normalized,
                "date_ist": date_ist,
            }
        if (
            not operation_policy["enabled"]
            and not force
        ):
            return {
                "status": "operation_disabled",
                "operation": normalized,
                "date_ist": date_ist,
            }
        if (
            policy["market_day_only"]
            and not session["market_day"]
            and not force
        ):
            return {
                "status": "skipped_non_market_day",
                "operation": normalized,
                "date_ist": date_ist,
                "session": session,
            }

        existing = self.repository.successful_run(
            normalized,
            date_ist,
        )
        if existing is not None and not force:
            return {
                "status": "already_completed",
                "operation": normalized,
                "date_ist": date_ist,
                "run": existing,
            }

        if not self._run_lock.acquire(blocking=False):
            return {
                "status": "busy",
                "operation": normalized,
                "date_ist": date_ist,
            }

        started_at = current.isoformat()
        try:
            steps: list[dict[str, Any]] = []
            limit = policy["market_context_limit"]

            if operation_policy["refresh_market_context"]:
                steps.append(
                    self._safe_call(
                        "market_context_refresh",
                        lambda: self._market_context_refresh(
                            limit=limit
                        ),
                    )
                )

            if (
                normalized == "eod"
                and operation_policy["paper_safety_tick"]
            ):
                steps.append(
                    self._safe_call(
                        "paper_safety_tick",
                        lambda: self._paper_safety_tick(
                            now=current
                        ),
                    )
                )

            if (
                normalized == "eod"
                and operation_policy["portfolio_sync"]
            ):
                steps.append(
                    self._safe_call(
                        "portfolio_sync",
                        self._portfolio_sync,
                    )
                )

            if normalized == "eod":
                steps.append(
                    self._safe_call(
                        "daily_pnl_snapshot",
                        self._daily_pnl,
                    )
                )

            failed_steps = sum(
                1
                for step in steps
                if step.get("status") == "failed"
            )
            completed_steps = sum(
                1
                for step in steps
                if step.get("status") == "completed"
            )
            status = (
                "degraded"
                if failed_steps
                else "completed"
            )
            run = {
                "run_id": str(uuid4()),
                "version": self.VERSION,
                "operation": normalized,
                "status": status,
                "date_ist": date_ist,
                "started_at_ist": started_at,
                "completed_at_ist": (
                    self.calendar.local_now().isoformat()
                ),
                "scheduled": bool(scheduled),
                "forced": bool(force),
                "market_day": session["market_day"],
                "market_phase": session["phase"],
                "completed_steps": completed_steps,
                "failed_steps": failed_steps,
                "steps": steps,
                "broker_orders_allowed": False,
            }
            self.repository.record_run(run)
            notification = self._notify(
                operation=normalized,
                run=run,
                deliver=operation_policy[
                    "notify_discord"
                ],
            )
            if notification is not None:
                run["notification"] = {
                    "status": notification.get("status"),
                    "event_id": notification.get("event_id"),
                    "error": notification.get("error"),
                }
            return run
        finally:
            self._run_lock.release()

    def external_contract(
        self,
        operation: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized = str(operation or "").strip().lower()
        if normalized not in self.OPERATIONS:
            raise ValueError(
                "operation must be morning or eod"
            )

        current = self.calendar.local_now(now)
        policy = self.policy()["policy"]
        operation_policy = policy[normalized]
        session = self.session(now=current)
        date_ist = session["date_ist"]

        scheduled_clock = datetime.strptime(
            operation_policy["time_ist"],
            "%H:%M",
        )
        scheduled_at = current.replace(
            hour=scheduled_clock.hour,
            minute=scheduled_clock.minute,
            second=0,
            microsecond=0,
        )
        window_end = scheduled_at + timedelta(
            minutes=int(
                operation_policy["grace_minutes"]
            )
        )

        existing = self.repository.successful_run(
            normalized,
            date_ist,
        )
        evidence = (
            {
                "run_id": existing.get("run_id"),
                "status": existing.get("status"),
                "completed_at_ist": existing.get(
                    "completed_at_ist"
                ),
            }
            if existing is not None
            else None
        )

        if not policy["automation_enabled"]:
            status = "not_required"
            reason = "automation_disabled"
        elif not operation_policy["enabled"]:
            status = "not_required"
            reason = "operation_disabled"
        elif (
            policy["market_day_only"]
            and not session["market_day"]
        ):
            status = "not_required"
            reason = "non_market_day"
        elif existing is not None:
            status = "satisfied"
            reason = "successful_run_recorded"
        elif current < scheduled_at:
            status = "pending"
            reason = "before_window"
        elif current <= window_end:
            status = "due"
            reason = "inside_window"
        else:
            status = "missed_window"
            reason = "window_elapsed_without_success"

        return {
            "status": status,
            "reason": reason,
            "operation": normalized,
            "date_ist": date_ist,
            "now_ist": current.isoformat(),
            "market_day": session["market_day"],
            "market_phase": session["phase"],
            "scheduled_time_ist": operation_policy[
                "time_ist"
            ],
            "grace_minutes": operation_policy[
                "grace_minutes"
            ],
            "window_start_ist": scheduled_at.isoformat(),
            "window_end_ist": window_end.isoformat(),
            "successful_run": evidence,
            "automation_enabled": policy[
                "automation_enabled"
            ],
            "operation_enabled": operation_policy[
                "enabled"
            ],
            "broker_orders_allowed": False,
        }

    def runs(
        self,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        rows = self.repository.runs(limit=limit)
        return {
            "status": "ready",
            "returned": len(rows),
            "runs": rows,
        }

    def control_center(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = self.calendar.local_now(now)
        policy_state = self.policy()
        session = self.session(now=current)

        breadth = {"status": "not_supported"}
        regime = {"status": "not_supported"}
        if self.market_context is not None:
            try:
                breadth = self.market_context.snapshot(
                    "breadth"
                )
            except Exception as exc:
                breadth = {
                    "status": "degraded",
                    "error": str(exc),
                }
            try:
                regime = self.market_context.snapshot(
                    "regime"
                )
            except Exception as exc:
                regime = {
                    "status": "degraded",
                    "error": str(exc),
                }

        portfolio_snapshot = {
            "status": "not_supported"
        }
        pnl = {"status": "not_supported"}
        if self.portfolio is not None:
            try:
                portfolio_snapshot = (
                    self.portfolio.portfolio()
                )
            except Exception as exc:
                portfolio_snapshot = {
                    "status": "degraded",
                    "error": str(exc),
                }
            try:
                pnl = self._daily_pnl()
            except Exception as exc:
                pnl = {
                    "status": "degraded",
                    "error": str(exc),
                }

        notification = {
            "status": "not_supported"
        }
        if self.notification_center is not None:
            try:
                notification = (
                    self.notification_center.readiness()
                )
            except Exception as exc:
                notification = {
                    "status": "degraded",
                    "error": str(exc),
                }

        return {
            "status": "ready",
            "version": self.VERSION,
            "now_ist": current.isoformat(),
            "session": session,
            "policy": policy_state,
            "latest_runs": self.repository.runs(limit=10),
            "market": {
                "breadth": breadth,
                "regime": regime,
            },
            "paper_monitor": self._safe_health(
                self.paper_monitor
            ),
            "portfolio": portfolio_snapshot,
            "daily_pnl": pnl,
            "notifications": notification,
            "safety": {
                "paper_only": True,
                "broker_orders_allowed": False,
                "automatic_scanner_execution": False,
            },
        }

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()


__all__ = ["MarketDayOperationsService"]
