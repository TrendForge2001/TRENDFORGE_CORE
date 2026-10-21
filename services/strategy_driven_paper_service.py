"""R72.5.4 strategy-driven paper-trading handoff.

This service does not create a new execution path. It selects a validated
multi-strategy BUY candidate, preserves scan/validation lineage, and delegates
all sizing and execution decisions to the canonical R67.2 PaperAutoEntryService.
"""
from __future__ import annotations

from datetime import datetime
import threading
from typing import Any

from scanner.strategy_registry import get_strategy


class StrategyDrivenPaperService:
    """Fail-closed bridge from R72.5 scanner/validation to R67.2 paper entry."""

    VERSION = "R72.5.4-v1"
    SUPPORTED_MODES = frozenset({"intraday", "swing"})

    def __init__(
        self,
        *,
        scanner_service: Any,
        paper_auto_entry: Any,
    ) -> None:
        if scanner_service is None:
            raise TypeError("scanner_service is required")
        if paper_auto_entry is None:
            raise TypeError("paper_auto_entry is required")
        self.scanner = scanner_service
        self.paper_auto_entry = paper_auto_entry
        self._lock = threading.Lock()
        self._execution_keys: set[tuple[str, str, str]] = set()
        self.preview_count = 0
        self.execution_requests = 0
        self.executed_count = 0
        self.blocked_count = 0
        self.last_result: dict[str, Any] | None = None

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _strategy_id(cls, value: Any) -> str:
        key = cls._clean(value).lower()
        if not key:
            raise ValueError("strategy_id is required")
        return key

    @classmethod
    def _run_id(cls, value: Any, field: str) -> str:
        run_id = cls._clean(value)
        if not run_id:
            raise ValueError(f"{field} is required")
        return run_id

    @staticmethod
    def _dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _rows(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [row for row in value if isinstance(row, dict)]

    def _scanner_result(self) -> tuple[dict[str, Any], dict[str, Any]]:
        snapshot = self.scanner.results()
        snapshot = self._dict(snapshot)
        return snapshot, self._dict(snapshot.get("last_result"))

    @classmethod
    def _validation_row(
        cls,
        validation_status: dict[str, Any],
        *,
        strategy_id: str,
        mode: str,
    ) -> dict[str, Any] | None:
        for row in cls._rows(validation_status.get("strategy_validation")):
            if (
                cls._clean(row.get("strategy_id")).lower() == strategy_id
                and cls._clean(row.get("mode")).lower() == mode
            ):
                return row
        return None

    @classmethod
    def _universe_passed(
        cls,
        validation_row: dict[str, Any],
        universe: str,
    ) -> bool:
        for row in cls._rows(validation_row.get("universe_gates")):
            if (
                cls._clean(row.get("universe")).upper() == universe.upper()
                and cls._clean(row.get("status")).upper() == "PASS"
            ):
                return True
        return False

    @classmethod
    def _strategy_evaluation(
        cls,
        candidate: dict[str, Any],
        strategy_id: str,
    ) -> dict[str, Any] | None:
        for row in cls._rows(candidate.get("strategy_evaluations")):
            if cls._clean(row.get("strategy_id")).lower() == strategy_id:
                return row
        return None

    @classmethod
    def _adapt_candidate(
        cls,
        *,
        candidate: dict[str, Any],
        evaluation: dict[str, Any],
        strategy_id: str,
        strategy: dict[str, Any],
        mode: str,
        scan_run_id: str,
        validation_run_id: str,
    ) -> dict[str, Any]:
        risk = cls._dict(evaluation.get("risk"))
        score = float(evaluation.get("score") or 0.0)
        confidence = float(candidate.get("consensus_score") or 0.0)
        entry = float(risk.get("entry") or 0.0)
        stoploss = float(risk.get("stoploss") or 0.0)
        target2 = float(risk.get("target2") or 0.0)
        return {
            "symbol": cls._clean(candidate.get("symbol")).upper(),
            "eligible": True,
            "execution_eligible": True,
            "ranking_score": score,
            "confidence": confidence,
            "technical_mode": mode,
            "strategy_id": strategy_id,
            "strategy_name": strategy.get("name"),
            "strategy_source": strategy.get("source"),
            "source_scan_run_id": scan_run_id,
            "validation_run_id": validation_run_id,
            "entry_bar_at": candidate.get("bar_at"),
            "signal": {
                "signal": "BUY",
                "overall_score": score,
                "confidence": confidence,
                "entry": entry,
                "stoploss": stoploss,
                "target2": target2,
            },
            "engines": {
                "Risk Engine": {
                    "metrics": {
                        "entry": entry,
                        "stoploss": stoploss,
                        "target2": target2,
                    }
                }
            },
        }

    def _prepare(
        self,
        *,
        strategy_id: str,
        scan_run_id: str,
        validation_run_id: str,
        validation_status: dict[str, Any],
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        strategy_id = self._strategy_id(strategy_id)
        scan_run_id = self._run_id(scan_run_id, "scan_run_id")
        validation_run_id = self._run_id(
            validation_run_id,
            "validation_run_id",
        )
        validation_status = self._dict(validation_status)

        blockers: list[str] = []
        try:
            strategy = get_strategy(strategy_id)
        except KeyError:
            strategy = {}
            blockers.append("strategy_not_registered")

        scanner_snapshot, scan = self._scanner_result()
        if not scan:
            blockers.append("scanner_result_unavailable")

        actual_scan_run = self._clean(scan.get("run_id"))
        if scan and actual_scan_run != scan_run_id:
            blockers.append("scan_run_id_mismatch")

        mode = self._clean(scan.get("mode")).lower()
        universe = self._clean(scan.get("universe")).upper()
        if mode not in self.SUPPORTED_MODES:
            blockers.append("paper_mode_not_supported")

        if strategy:
            if not bool(strategy.get("paper_eligible")):
                blockers.append("registry_not_paper_eligible")
            if mode and mode not in set(strategy.get("modes") or []):
                blockers.append("strategy_mode_mismatch")

        scan_status = self._clean(scan.get("status")).lower()
        requested = int(scan.get("requested_symbols") or 0)
        completed = int(scan.get("completed_symbols") or 0)
        errors = int(scan.get("error_symbols") or 0)
        if scan and (
            scan_status != "completed"
            or errors != 0
            or requested <= 0
            or completed != requested
        ):
            blockers.append("scan_not_fully_completed")

        if self._clean(validation_status.get("status")).lower() != "completed":
            blockers.append("validation_not_completed")
        if self._clean(validation_status.get("run_id")) != validation_run_id:
            blockers.append("validation_run_id_mismatch")

        validation_row = self._validation_row(
            validation_status,
            strategy_id=strategy_id,
            mode=mode,
        )
        if validation_row is None:
            blockers.append("strategy_validation_missing")
        else:
            if (
                self._clean(validation_row.get("promotion_status")).upper()
                != "ELIGIBLE_FOR_REVIEW"
            ):
                blockers.append("strategy_not_validation_eligible")
            if not bool(validation_row.get("registry_paper_eligible")):
                blockers.append("validation_registry_not_paper_eligible")
            if universe and not self._universe_passed(
                validation_row,
                universe,
            ):
                blockers.append("scanner_universe_not_validation_passed")

        auto_health = (
            self.paper_auto_entry.health()
            if callable(getattr(self.paper_auto_entry, "health", None))
            else {}
        )
        if not bool(self._dict(auto_health).get("enabled")):
            blockers.append("r67_2_auto_entry_disabled")
        paper_service = getattr(self.paper_auto_entry, "paper_service", None)
        if paper_service is not None and not bool(
            getattr(paper_service, "can_open_new_positions", False)
        ):
            blockers.append("paper_trading_not_ready")

        blockers = list(dict.fromkeys(blockers))
        candidate_rows: list[dict[str, Any]] = []
        adapters: list[dict[str, Any]] = []

        if not blockers:
            for candidate in self._rows(scan.get("top_picks")):
                consensus = self._clean(candidate.get("consensus")).upper()
                if consensus not in {"BUY", "STRONG_BUY"}:
                    continue
                evaluation = self._strategy_evaluation(
                    candidate,
                    strategy_id,
                )
                if evaluation is None:
                    continue
                if (
                    self._clean(evaluation.get("status")).lower() != "evaluated"
                    or self._clean(evaluation.get("signal")).upper() != "BUY"
                    or not bool(evaluation.get("paper_eligible", True))
                ):
                    continue
                adapter = self._adapt_candidate(
                    candidate=candidate,
                    evaluation=evaluation,
                    strategy_id=strategy_id,
                    strategy=strategy,
                    mode=mode,
                    scan_run_id=scan_run_id,
                    validation_run_id=validation_run_id,
                )
                gate = self.paper_auto_entry.evaluate_candidate(
                    adapter,
                    now=now,
                )
                candidate_rows.append(
                    {
                        "symbol": adapter["symbol"],
                        "strategy_id": strategy_id,
                        "strategy_name": strategy.get("name"),
                        "strategy_score": adapter["ranking_score"],
                        "consensus": consensus,
                        "consensus_score": adapter["confidence"],
                        "entry": adapter["signal"]["entry"],
                        "stoploss": adapter["signal"]["stoploss"],
                        "target2": adapter["signal"]["target2"],
                        "r67_2_approved": bool(gate.get("approved")),
                        "r67_2_reasons": list(gate.get("reasons") or []),
                        "r67_2_quantity": int(gate.get("quantity") or 0),
                    }
                )
                adapters.append(adapter)

        approved_count = sum(
            1 for row in candidate_rows if row.get("r67_2_approved")
        )
        status = (
            "blocked"
            if blockers
            else "no_candidates"
            if not candidate_rows
            else "ready"
            if approved_count > 0
            else "risk_blocked"
        )
        preview = {
            "status": status,
            "version": self.VERSION,
            "strategy_id": strategy_id,
            "strategy_name": strategy.get("name"),
            "mode": mode or None,
            "universe": universe or None,
            "scan_run_id": scan_run_id,
            "validation_run_id": validation_run_id,
            "scanner_status": scanner_snapshot.get("scanner_status"),
            "blockers": blockers,
            "candidate_count": len(candidate_rows),
            "r67_2_approved_count": approved_count,
            "candidates": candidate_rows,
            "validation": validation_row,
            "safety": {
                "paper_only": True,
                "broker_orders_allowed": False,
                "r67_2_gate_required": True,
                "paper_kill_switch_bypass_allowed": False,
                "live_trading_allowed": False,
            },
        }
        return preview, adapters

    def preview(
        self,
        *,
        strategy_id: str,
        scan_run_id: str,
        validation_run_id: str,
        validation_status: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.preview_count += 1
        preview, _ = self._prepare(
            strategy_id=strategy_id,
            scan_run_id=scan_run_id,
            validation_run_id=validation_run_id,
            validation_status=validation_status,
            now=now,
        )
        self.last_result = preview
        return preview

    def execute(
        self,
        *,
        strategy_id: str,
        scan_run_id: str,
        validation_run_id: str,
        validation_status: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.execution_requests += 1
        preview, adapters = self._prepare(
            strategy_id=strategy_id,
            scan_run_id=scan_run_id,
            validation_run_id=validation_run_id,
            validation_status=validation_status,
            now=now,
        )
        if preview["status"] != "ready":
            self.blocked_count += 1
            result = {
                **preview,
                "execution_status": "blocked",
                "paper_result": None,
            }
            self.last_result = result
            return result

        key = (
            self._run_id(scan_run_id, "scan_run_id"),
            self._run_id(validation_run_id, "validation_run_id"),
            self._strategy_id(strategy_id),
        )
        with self._lock:
            if key in self._execution_keys:
                self.blocked_count += 1
                result = {
                    **preview,
                    "status": "blocked",
                    "execution_status": "blocked",
                    "blockers": [
                        *preview.get("blockers", []),
                        "execution_already_requested_for_lineage",
                    ],
                    "paper_result": None,
                }
                self.last_result = result
                return result
            self._execution_keys.add(key)

        approved_symbols = {
            row["symbol"]
            for row in preview["candidates"]
            if row.get("r67_2_approved")
        }
        execution_candidates = [
            row
            for row in adapters
            if row.get("symbol") in approved_symbols
        ]
        paper_result = self.paper_auto_entry.process_scan(
            {
                "outcome": "completed",
                "top_picks": execution_candidates,
                "execution_top_picks": execution_candidates,
            },
            run_id=(
                f"r7254:{scan_run_id}:{strategy_id}:"
                f"{validation_run_id}"
            ),
            execute_requested=True,
            continuation=False,
            now=now,
        )
        opened_count = int(self._dict(paper_result).get("opened_count") or 0)
        self.executed_count += opened_count
        result = {
            **preview,
            "status": self._clean(
                self._dict(paper_result).get("status")
            ).lower()
            or "unknown",
            "execution_status": self._dict(paper_result).get("status"),
            "paper_result": paper_result,
            "safety": {
                **preview["safety"],
                "paper_orders_created": opened_count,
                "broker_orders_created": 0,
            },
        }
        self.last_result = result
        return result

    def readiness(
        self,
        *,
        validation_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validation_status = self._dict(validation_status)
        scanner_snapshot, scan = self._scanner_result()
        auto_health = (
            self.paper_auto_entry.health()
            if callable(getattr(self.paper_auto_entry, "health", None))
            else {}
        )
        rows = self._rows(validation_status.get("strategy_validation"))
        eligible = [
            row
            for row in rows
            if self._clean(row.get("promotion_status")).upper()
            == "ELIGIBLE_FOR_REVIEW"
            and bool(row.get("registry_paper_eligible"))
            and self._clean(row.get("mode")).lower()
            in self.SUPPORTED_MODES
        ]
        paper_service = getattr(self.paper_auto_entry, "paper_service", None)
        paper_ready = bool(
            getattr(paper_service, "can_open_new_positions", False)
        )
        auto_enabled = bool(self._dict(auto_health).get("enabled"))
        return {
            "status": (
                "ready"
                if auto_enabled and paper_ready
                else "blocked"
            ),
            "version": self.VERSION,
            "supported_modes": sorted(self.SUPPORTED_MODES),
            "latest_scan_run_id": scan.get("run_id"),
            "latest_scan_status": scan.get("status"),
            "latest_scan_universe": scan.get("universe"),
            "latest_scan_mode": scan.get("mode"),
            "validation_status": validation_status.get("status"),
            "validation_run_id": validation_status.get("run_id"),
            "eligible_strategy_count": len(eligible),
            "eligible_strategies": eligible,
            "r67_2": auto_health,
            "paper_trading_ready": paper_ready,
            "preview_count": self.preview_count,
            "execution_requests": self.execution_requests,
            "opened_count": self.executed_count,
            "lineage_execution_keys": len(self._execution_keys),
            "scanner_snapshot_source": scanner_snapshot.get("source"),
            "safety": {
                "paper_only": True,
                "broker_orders_allowed": False,
                "requires_admin_execute": True,
                "requires_completed_scan": True,
                "requires_r7253_validation_pass": True,
                "requires_registry_paper_eligible": True,
                "requires_r67_2_gate": True,
                "paper_kill_switch_bypass_allowed": False,
                "supported_modes": sorted(self.SUPPORTED_MODES),
            },
        }

    def health(self) -> dict[str, Any]:
        return self.readiness(validation_status={})


__all__ = ["StrategyDrivenPaperService"]
