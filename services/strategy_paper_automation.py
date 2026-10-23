"""Operator-controlled, restart-conservative saved-strategy paper automation."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from contextlib import nullcontext, suppress
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from providers.kite_paper_quotes import FreshKitePaperQuotes
from scanner.multi_strategy_engine import CONFIRMATION_ONLY, REVIEW_REQUIRED
from scanner.strategy_registry import list_strategies
from services.technical_trading_service import TechnicalTradingService


class StrategyPaperAutomation:
    CONFIG_KEY = "paper.automation.config.v1"
    TZ = ZoneInfo("Asia/Kolkata")

    def __init__(
        self,
        *,
        scanner: Any,
        bridge: Any,
        repository: Any,
        quote_provider: FreshKitePaperQuotes,
        paper_monitor: Any,
        strategy_monitor: Any,
        validation_getter: Callable[[], dict],
        validation_starter: Callable[[], dict],
        clock: Callable[[], datetime] | None = None,
    ):
        self.scanner, self.bridge, self.repository = scanner, bridge, repository
        self.quotes, self.paper_monitor = quote_provider, paper_monitor
        self.strategy_monitor = strategy_monitor
        self.paper = bridge.paper_auto_entry.paper_service
        self.validation_getter, self.validation_starter = (
            validation_getter,
            validation_starter,
        )
        self.clock = clock or (lambda: datetime.now(self.TZ))
        self._control = threading.RLock()
        self._run_lock = threading.Lock()
        self._enabled = False
        self._generation = 0
        self._stopping = False
        self._validation_attempted = False
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._phase = "off"
        self._last_error: str | None = None
        self._last_cycle: dict = {}
        self._last_exits: str | None = None
        self._last_checked_at: str | None = None
        self._persistence_error = False
        self._resume_required = False
        try:
            saved = repository.load_state(self.CONFIG_KEY)
            config = saved.get("payload", {}) if isinstance(saved, dict) else {}
            self._resume_required = config.get("enabled") is True
        except Exception:
            self._persistence_error = True
        # Existing positions retain fresh-quote exits even after entries are OFF.
        self.paper_monitor.quote_provider = self.quotes
        self.strategy_monitor.quote_provider = self.quotes
        self.strategy_monitor.require_fresh_candles = True

    def _now(self) -> datetime:
        value = self.clock()
        return (
            value.replace(tzinfo=self.TZ)
            if value.tzinfo is None
            else value.astimezone(self.TZ)
        )

    def configure(self, enabled: bool) -> dict:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        # Same ordering as final fill admission: paper entry lock, then control.
        with getattr(self.paper, "_entry_lock", nullcontext()), self._control:
            if not enabled:
                self._enabled = False
                self._generation += 1
                self._phase = "off"
            try:
                self.repository.save_state(
                    self.CONFIG_KEY,
                    "paper_automation_config",
                    {
                        "enabled": enabled,
                        "updated_at": self._now().isoformat(),
                    },
                )
            except Exception:
                self._persistence_error = True
                if enabled:
                    raise RuntimeError(
                        "Automation settings could not be saved"
                    ) from None
            else:
                self._persistence_error = False
            if enabled:
                self._generation += 1
                self._enabled = True
                self._validation_attempted = False
                self._phase = "armed"
            self._resume_required = False
        return self.status()

    def _admit(self, generation: int, candidate: dict) -> bool:
        if self._blockers():
            return False
        with self._control:
            if not self._enabled or self._stopping or generation != self._generation:
                return False
        now = self._now()
        if now.weekday() >= 5 or not time(9, 30) <= now.time() < time(14, 45):
            return False
        try:
            frame = pd.DataFrame(index=pd.DatetimeIndex([candidate["entry_bar_at"]]))
            if TechnicalTradingService._execution_block_reason(
                frame,
                mode=candidate["technical_mode"],
                now=now,
            ):
                return False
            stamp = datetime.fromisoformat(candidate["automation_quote_at"])
            return -5 <= (now - stamp).total_seconds() <= self.quotes.max_age_seconds
        except (KeyError, TypeError, ValueError):
            return False

    def _live_candidate(self, candidate: dict) -> dict:
        now = self._now()
        frame = pd.DataFrame(index=pd.DatetimeIndex([candidate.get("entry_bar_at")]))
        reason = TechnicalTradingService._execution_block_reason(
            frame,
            mode=candidate["technical_mode"],
            now=now,
        )
        if reason:
            raise ValueError("A current completed candle is required")
        instrument = "NSE:" + candidate["symbol"]
        quote = self.quotes.prices([instrument], now=now)[instrument]
        candidate["signal"] = {**candidate["signal"], "entry": quote["last_price"]}
        engines = dict(candidate.get("engines") or {})
        risk = dict(engines.get("Risk Engine") or {})
        risk["metrics"] = {**risk.get("metrics", {}), "entry": quote["last_price"]}
        candidate["engines"] = {**engines, "Risk Engine": risk}
        candidate["automation_quote_at"] = quote["timestamp"]
        return candidate

    def _blockers(self) -> list[str]:
        health = self.paper.health()
        blockers = []
        if health.get("enabled") is not True:
            blockers.append("paper_trading_disabled")
        if health.get("kill_switch") is not False:
            blockers.append("paper_kill_switch_active")
        policy = health.get("entry_storage_policy") or {}
        if (
            policy.get("entry_allowed") is not True
            or policy.get("mode") != "durable"
            or policy.get("verified_persistent") is not True
        ):
            blockers.append(str(policy.get("reason") or "verified_storage_required"))
        if health.get("can_open_new_positions") is not True:
            blockers.append("paper_runtime_not_ready")
        if self.bridge.paper_auto_entry.enabled is not True:
            blockers.append("paper_auto_entry_disabled")
        if self._persistence_error:
            blockers.append("automation_settings_unavailable")
        return blockers

    def status(self) -> dict:
        with self._control:
            enabled, phase = self._enabled, self._phase
        blockers = self._blockers()
        return {
            "enabled": enabled,
            "phase": "blocked" if enabled and blockers else phase,
            "blockers": blockers,
            "busy": self._run_lock.locked(),
            "worker_running": self._task is not None and not self._task.done(),
            "resume_required": self._resume_required,
            "settings_saved": not self._persistence_error,
            "universe": "NIFTY 100",
            "poll_seconds": 15,
            "last_checked_at": self._last_checked_at,
            "last_error": self._last_error,
            "last_cycle": self._last_cycle,
            "strategies": [
                {
                    "strategy_id": row["strategy_id"],
                    "name": row["name"],
                    "modes": row["modes"],
                    "paper_eligible": row["paper_eligible"],
                    "entry_policy": "review_required"
                    if row["strategy_id"] in REVIEW_REQUIRED
                    else "confirmation_only"
                    if row["strategy_id"] in CONFIRMATION_ONLY
                    else "validation_and_risk_required",
                }
                for row in list_strategies()
            ],
            "paper_only": True,
            "broker_orders_allowed": False,
            "portfolio_policy": "shared_capital_one_position_per_symbol",
        }

    def tick(self) -> dict:
        if not self._run_lock.acquire(blocking=False):
            return {"status": "busy"}
        try:
            now = self._now()
            self._last_checked_at = now.isoformat()
            snapshot = self.paper.runtime.snapshot()
            strategy_positions = any(
                row.get("strategy_id") for row in snapshot["positions"]
            )
            if (
                strategy_positions
                and now.weekday() < 5
                and time(9, 15) <= now.time() <= time(15, 30)
            ):
                self.paper_monitor.tick(now=now)
                slot = now.strftime("%Y%m%d%H") + str(now.minute // 15)
                if slot != self._last_exits:
                    self.strategy_monitor.tick(now=now, force=True)
                    self._last_exits = slot
            with self._control:
                enabled, generation = self._enabled, self._generation
            if not enabled or self._stopping:
                return {"status": "off", "monitoring_existing": strategy_positions}
            if self._blockers():
                self._phase = "blocked"
                return {"status": "blocked", "blockers": self._blockers()}
            if now.weekday() >= 5 or not time(9, 30) <= now.time() < time(14, 45):
                self._phase = "waiting_for_market"
                return {"status": self._phase}
            validation = self.validation_getter()
            request = validation.get("request") or {}
            covers_catalog = (
                request.get("source") == "all"
                and "NIFTY 100" in request.get("universes", [])
                and set(request.get("modes", [])) >= {"intraday", "swing", "positional"}
                and not request.get("limit")
                and not request.get("strategy_ids")
                and bool(validation.get("run_id"))
            )
            if validation.get("status") != "completed" or not covers_catalog:
                self._phase = "validating_strategies"
                if (
                    validation.get("status") not in {"running", "starting"}
                    and not self._validation_attempted
                ):
                    self._validation_attempted = True
                    self.validation_starter()
                return {"status": self._phase}
            outcomes = []
            for mode in ("intraday", "swing", "positional"):
                with self._control:
                    if (
                        not self._enabled
                        or self._generation != generation
                        or self._stopping
                    ):
                        break
                due = now.strftime("%Y%m%d")
                if mode == "intraday":
                    due += f"T{now.hour:02d}{(now.minute // 15) * 15:02d}"
                run_id = f"auto:{mode}:{due}"
                if not self.repository.claim_execution(
                    scan_run_id=run_id,
                    validation_run_id=validation["run_id"],
                    strategy_id=f"automation_{mode}",
                    payload={"paper_only": True},
                ):
                    continue
                self._phase = f"scanning_{mode}"
                scan = self.scanner.scan(
                    universe="NIFTY 100",
                    mode=mode,
                    source="all",
                    top_n=100,
                    run_id=run_id,
                    now=self._now(),
                )
                for strategy_id in scan.get("strategy_ids", []):
                    with self._control:
                        if (
                            not self._enabled
                            or self._generation != generation
                            or self._stopping
                        ):
                            break
                    if mode not in self.bridge.SUPPORTED_MODES:
                        outcomes.append(
                            {
                                "strategy_id": strategy_id,
                                "mode": mode,
                                "status": "blocked",
                                "blockers": ["paper_mode_not_supported"],
                            }
                        )
                        continue
                    response = self.bridge.execute(
                        strategy_id=strategy_id,
                        scan_run_id=run_id,
                        validation_run_id=validation["run_id"],
                        validation_status=validation,
                        now=self._now(),
                        admission_guard=lambda candidate: self._admit(
                            generation, candidate
                        ),
                        candidate_transform=self._live_candidate,
                    )
                    paper = response.get("paper_result") or {}
                    outcomes.append(
                        {
                            "strategy_id": strategy_id,
                            "mode": mode,
                            "status": response.get("status"),
                            "blockers": response.get("blockers", []),
                            "opened_count": paper.get("opened_count", 0),
                            "rejections": [
                                row.get("reasons", [])
                                for row in paper.get("evaluations", [])
                                if row.get("approved") is not True
                            ],
                        }
                    )
            if outcomes:
                self._last_cycle = {
                    "checked_at": self._now().isoformat(),
                    "strategies": outcomes,
                }
            self._last_error = None
            self._phase = "watching_market" if self._enabled else "off"
            return {"status": self._phase, **self._last_cycle}
        except Exception:
            self._last_error = (
                "Automation cycle unavailable; inspect server health "
                "and saved strategy validation."
            )
            self._phase = "error" if self._enabled else "off"
            return {"status": self._phase, "error": self._last_error}
        finally:
            self._run_lock.release()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.to_thread(self.tick)
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=15)

    async def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return False
        self._stopping = False
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(
            self._loop(), name="saved-strategy-paper-automation"
        )
        return True

    async def stop(self) -> bool:
        with getattr(self.paper, "_entry_lock", nullcontext()), self._control:
            self._stopping = True
            self._stop.set()
        if self._task is None:
            return True
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=5)
        except TimeoutError:
            return False
        return True
