"""NIFTY 500 technical auto-scanner for paper-only market sessions."""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
import os
import threading
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from providers.nse_broad_market_constituents import (
    NSEBroadMarketConstituentProvider,
)


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _clock(name: str, default: str) -> time:
    raw = str(os.getenv(name) or default).strip()
    try:
        hour, minute = (int(part) for part in raw.split(":", 1))
        return time(hour, minute)
    except Exception:
        hour, minute = (int(part) for part in default.split(":", 1))
        return time(hour, minute)


class TechnicalAutoScanner:
    """Run completed-bar NIFTY 500 scans and route BUYs to paper controls."""

    VERSION = "R72.3-v1"
    MARKET_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(
        self,
        *,
        technical_service: Any,
        paper_auto_entry: Any | None = None,
        universe_provider: NSEBroadMarketConstituentProvider | None = None,
    ) -> None:
        if technical_service is None:
            raise ValueError("technical_service is required")
        self.technical = technical_service
        self.paper_auto_entry = paper_auto_entry
        self.universe_provider = (
            universe_provider or NSEBroadMarketConstituentProvider()
        )
        self.enabled = _flag("TRENDFORGE_TECHNICAL_AUTO_SCAN_ENABLED", False)
        self.intraday_enabled = _flag(
            "TRENDFORGE_TECHNICAL_INTRADAY_ENABLED", True
        )
        self.swing_enabled = _flag(
            "TRENDFORGE_TECHNICAL_SWING_ENABLED", True
        )
        self.paper_execution = _flag(
            "TRENDFORGE_TECHNICAL_AUTO_PAPER_ENABLED", True
        )
        self.intraday_start = _clock(
            "TRENDFORGE_TECHNICAL_INTRADAY_START_IST", "09:30"
        )
        self.intraday_end = _clock(
            "TRENDFORGE_TECHNICAL_INTRADAY_END_IST", "14:45"
        )
        self.swing_time = _clock(
            "TRENDFORGE_TECHNICAL_SWING_TIME_IST", "09:25"
        )
        self.swing_grace_minutes = max(
            1,
            min(
                60,
                int(
                    os.getenv(
                        "TRENDFORGE_TECHNICAL_SWING_GRACE_MINUTES",
                        "20",
                    )
                ),
            ),
        )
        self.poll_seconds = max(
            15,
            int(os.getenv("TRENDFORGE_TECHNICAL_AUTO_SCAN_POLL_SECONDS", "30")),
        )
        self.chunk_size = max(
            25,
            min(
                100,
                int(os.getenv("TRENDFORGE_TECHNICAL_AUTO_SCAN_CHUNK_SIZE", "100")),
            ),
        )
        self.top_n = max(
            1,
            min(
                50,
                int(os.getenv("TRENDFORGE_TECHNICAL_AUTO_SCAN_TOP_N", "20")),
            ),
        )
        self._run_lock = threading.Lock()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._slots_seen: set[str] = set()
        self._last_results: dict[str, dict[str, Any]] = {}
        self._last_error: str | None = None
        self._started_at: str | None = None

    @staticmethod
    def _chunks(values: list[str], size: int):
        for start in range(0, len(values), size):
            yield values[start : start + size]

    @staticmethod
    def _paper_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for item in rows:
            if not item.get("execution_eligible"):
                continue
            output.append(
                {
                    "symbol": item["symbol"],
                    "execution_eligible": True,
                    "ranking_score": item.get("score"),
                    "confidence": item.get("confidence"),
                    "signal": {
                        "signal": "BUY",
                        "overall_score": item.get("score"),
                        "confidence": item.get("confidence"),
                        "entry": item.get("entry"),
                        "stoploss": item.get("stoploss"),
                        "target2": item.get("target2"),
                    },
                    "technical_mode": item.get("mode"),
                    "technical_trigger": item.get("trigger"),
                }
            )
        return output

    def _symbols(self, *, force_refresh: bool = False) -> list[str]:
        payload = self.universe_provider.load(
            "NIFTY 500",
            force_refresh=force_refresh,
        )
        symbols = [
            str(item.get("symbol") or "").strip().upper()
            for item in payload.get("members") or []
            if str(item.get("symbol") or "").strip()
        ]
        if len(symbols) < 500:
            raise RuntimeError(
                f"NIFTY 500 universe incomplete: {len(symbols)} symbols"
            )
        return symbols

    def run_once(
        self,
        mode: str,
        *,
        execute_paper: bool | None = None,
        force_refresh_universe: bool = False,
    ) -> dict[str, Any]:
        normalized = str(mode or "").strip().lower()
        if normalized not in {"intraday", "swing"}:
            raise ValueError("mode must be intraday or swing")
        if not self._run_lock.acquire(blocking=False):
            return {
                "status": "busy",
                "mode": normalized,
                "version": self.VERSION,
            }

        started = datetime.now(self.MARKET_TZ)
        run_id = f"r723-{normalized}-{uuid4().hex[:12]}"
        try:
            symbols = self._symbols(
                force_refresh=force_refresh_universe
            )
            results: list[dict[str, Any]] = []
            top_picks: list[dict[str, Any]] = []
            batch_errors: list[dict[str, Any]] = []

            for batch_number, chunk in enumerate(
                self._chunks(symbols, self.chunk_size),
                start=1,
            ):
                try:
                    from scanner.workspace_strategies import strategy_choices
                    response = self.technical.scan(
                        symbols=chunk,
                        mode=normalized,
                        strategy_id=next(iter(strategy_choices(normalized).values())),
                        top_n=min(100, len(chunk)),
                        execute_paper=False,
                        run_id=f"{run_id}-b{batch_number}",
                    )
                    results.extend(response.get("results") or [])
                    top_picks.extend(response.get("top_picks") or [])
                except Exception as exc:
                    batch_errors.append(
                        {
                            "batch": batch_number,
                            "symbols": len(chunk),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

            ranked = sorted(
                [item for item in top_picks if isinstance(item, dict)],
                key=lambda item: float(item.get("score") or 0.0),
                reverse=True,
            )
            selected = ranked[: self.top_n]
            requested_paper = (
                self.paper_execution
                if execute_paper is None
                else bool(execute_paper)
            )
            paper: dict[str, Any] = {
                "status": "not_requested",
                "opened": [],
                "broker_orders_allowed": False,
            }
            if requested_paper and self.paper_auto_entry is not None:
                candidates = self._paper_candidates(selected)
                paper = self.paper_auto_entry.process_scan(
                    {
                        "outcome": "completed",
                        "top_picks": candidates,
                        "execution_top_picks": candidates,
                    },
                    run_id=run_id,
                    execute_requested=True,
                    continuation=False,
                    now=started,
                )

            completed = sum(
                1 for item in results
                if item.get("signal") != "ERROR"
            )
            errors = sum(
                1 for item in results
                if item.get("signal") == "ERROR"
            )
            payload = {
                "status": "completed" if not batch_errors else "degraded",
                "version": self.VERSION,
                "run_id": run_id,
                "mode": normalized,
                "universe": "NIFTY 500",
                "started_at_ist": started.isoformat(),
                "completed_at_ist": datetime.now(self.MARKET_TZ).isoformat(),
                "requested_symbols": len(symbols),
                "completed_symbols": completed,
                "error_symbols": errors,
                "buy_candidates": len(ranked),
                "top_picks": selected,
                "batch_errors": batch_errors,
                "paper": paper,
                "safety": {
                    "paper_only": True,
                    "broker_orders_allowed": False,
                    "fundamentals_used": False,
                    "execute_paper_requested": requested_paper,
                },
            }
            self._last_results[normalized] = payload
            self._last_error = None
            return payload
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            payload = {
                "status": "failed",
                "version": self.VERSION,
                "run_id": run_id,
                "mode": normalized,
                "universe": "NIFTY 500",
                "error": self._last_error,
                "paper": {
                    "status": "not_executed",
                    "broker_orders_allowed": False,
                },
            }
            self._last_results[normalized] = payload
            return payload
        finally:
            self._run_lock.release()

    def _intraday_slot(self, now: datetime) -> str | None:
        if not (
            self.intraday_enabled
            and self.intraday_start <= now.time() <= self.intraday_end
        ):
            return None
        minute = (now.minute // 15) * 15
        slot = now.replace(minute=minute, second=0, microsecond=0)
        if slot.time() < self.intraday_start:
            return None
        return f"intraday:{slot.date().isoformat()}:{slot.strftime('%H:%M')}"

    def _swing_slot(self, now: datetime) -> str | None:
        """Return today's swing slot only inside the bounded morning window.

        A Render restart later in the day must not backfill a missed morning
        scan. Without this guard, every after-hours process restart can launch
        a full NIFTY 500 scan and starve the single-instance liveness probe.
        """
        if not self.swing_enabled:
            return None
        scheduled = now.replace(
            hour=self.swing_time.hour,
            minute=self.swing_time.minute,
            second=0,
            microsecond=0,
        )
        deadline = scheduled + timedelta(minutes=self.swing_grace_minutes)
        if now < scheduled or now > deadline:
            return None
        return f"swing:{now.date().isoformat()}"

    async def _loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(self.MARKET_TZ)
            if now.weekday() < 5:
                due: list[tuple[str, str]] = []
                swing_slot = self._swing_slot(now)
                if swing_slot and swing_slot not in self._slots_seen:
                    due.append(("swing", swing_slot))
                intraday_slot = self._intraday_slot(now)
                if intraday_slot and intraday_slot not in self._slots_seen:
                    due.append(("intraday", intraday_slot))

                for mode, slot in due:
                    self._slots_seen.add(slot)
                    await asyncio.to_thread(
                        self.run_once,
                        mode,
                        execute_paper=self.paper_execution,
                    )

            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.poll_seconds,
                )
            except asyncio.TimeoutError:
                pass

    async def start(self) -> bool:
        if not self.enabled:
            return False
        if self._task is not None and not self._task.done():
            return True
        self._stop = asyncio.Event()
        self._started_at = datetime.now(self.MARKET_TZ).isoformat()
        self._task = asyncio.create_task(
            self._loop(),
            name="trendforge-technical-auto-scanner",
        )
        return True

    async def stop(self) -> None:
        self._stop.set()
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._task, timeout=5)
        except Exception:
            self._task.cancel()
        finally:
            self._task = None

    def trigger(
        self,
        mode: str,
        *,
        execute_paper: bool = False,
    ) -> dict[str, Any]:
        if self._run_lock.locked():
            return {"status": "busy", "mode": str(mode).lower()}
        thread = threading.Thread(
            target=self.run_once,
            kwargs={
                "mode": mode,
                "execute_paper": bool(execute_paper),
            },
            name=f"trendforge-manual-{mode}-scan",
            daemon=True,
        )
        thread.start()
        return {
            "status": "started",
            "mode": str(mode).strip().lower(),
            "paper_execution_requested": bool(execute_paper),
        }

    def status(self) -> dict[str, Any]:
        return {
            "status": (
                "running"
                if self._task is not None and not self._task.done()
                else "configured"
                if self.enabled
                else "disabled"
            ),
            "version": self.VERSION,
            "enabled": self.enabled,
            "universe": "NIFTY 500",
            "intraday_enabled": self.intraday_enabled,
            "swing_enabled": self.swing_enabled,
            "paper_execution": self.paper_execution,
            "intraday_start_ist": self.intraday_start.strftime("%H:%M"),
            "intraday_end_ist": self.intraday_end.strftime("%H:%M"),
            "swing_time_ist": self.swing_time.strftime("%H:%M"),
            "poll_seconds": self.poll_seconds,
            "chunk_size": self.chunk_size,
            "top_n": self.top_n,
            "started_at": self._started_at,
            "busy": self._run_lock.locked(),
            "last_error": self._last_error,
            "last_results": self._last_results,
            "safety": {
                "paper_only": True,
                "broker_orders_allowed": False,
                "fundamentals_used": False,
            },
        }


__all__ = ["TechnicalAutoScanner"]
