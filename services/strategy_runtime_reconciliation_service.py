"""R72.5.6 restart-safe strategy runtime reconciliation."""
from __future__ import annotations

from typing import Any


class StrategyRuntimeReconciliationService:
    """Read-only audit of persistent strategy lineage and open paper positions."""

    VERSION = "R72.5.6-v1"

    def __init__(
        self,
        *,
        state_repository: Any,
        paper_service: Any,
    ) -> None:
        if state_repository is None:
            raise TypeError("state_repository is required")
        if paper_service is None:
            raise TypeError("paper_service is required")
        self.state_repository = state_repository
        self.paper_service = paper_service

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _payload(row: Any) -> dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        payload = row.get("payload")
        return payload if isinstance(payload, dict) else {}

    def _state_exists(self, key: str) -> bool:
        method = getattr(self.state_repository, "load_state", None)
        if not callable(method):
            return False
        try:
            return isinstance(method(key), dict)
        except Exception:
            return False

    def _strategy_positions(self) -> list[dict[str, Any]]:
        runtime = getattr(self.paper_service, "runtime", None)
        portfolio = getattr(runtime, "portfolio", None)
        positions = getattr(portfolio, "positions", {})
        if not isinstance(positions, dict):
            return []

        rows: list[dict[str, Any]] = []
        for symbol, position in positions.items():
            strategy_id = self._clean(
                getattr(position, "strategy_id", None)
            ).lower()
            if not strategy_id:
                continue
            rows.append(
                {
                    "symbol": self._clean(symbol).upper(),
                    "strategy_id": strategy_id,
                    "strategy_name": getattr(
                        position, "strategy_name", None
                    ),
                    "trade_mode": self._clean(
                        getattr(position, "trade_mode", None)
                    ).lower(),
                    "source_scan_run_id": self._clean(
                        getattr(position, "source_scan_run_id", None)
                    ),
                    "validation_run_id": self._clean(
                        getattr(position, "validation_run_id", None)
                    ),
                }
            )
        return rows

    def reconciliation(self) -> dict[str, Any]:
        load = getattr(self.state_repository, "load_state", None)
        health = getattr(self.state_repository, "health", None)
        storage = (
            health()
            if callable(health)
            else {"status": "unknown"}
        )

        latest_scanner = (
            load("r72.5.latest_scanner")
            if callable(load)
            else None
        )
        latest_validation = (
            load("r72.5.latest_validation")
            if callable(load)
            else None
        )
        scanner_payload = self._payload(latest_scanner)
        validation_payload = self._payload(latest_validation)

        claim_method = getattr(
            self.state_repository,
            "has_execution_claim",
            None,
        )
        rows: list[dict[str, Any]] = []
        consistent = 0
        incomplete = 0
        for position in self._strategy_positions():
            scan_run_id = position["source_scan_run_id"]
            validation_run_id = position["validation_run_id"]
            strategy_id = position["strategy_id"]

            scan_present = bool(
                scan_run_id
                and self._state_exists(
                    f"r72.5.scanner:{scan_run_id}"
                )
            )
            validation_present = bool(
                validation_run_id
                and self._state_exists(
                    f"r72.5.validation:{validation_run_id}"
                )
            )
            execution_claim_present = False
            if (
                callable(claim_method)
                and scan_run_id
                and validation_run_id
                and strategy_id
            ):
                try:
                    execution_claim_present = bool(
                        claim_method(
                            scan_run_id=scan_run_id,
                            validation_run_id=validation_run_id,
                            strategy_id=strategy_id,
                        )
                    )
                except Exception:
                    execution_claim_present = False

            lineage_ok = bool(
                scan_present
                and validation_present
                and execution_claim_present
            )
            if lineage_ok:
                consistent += 1
            else:
                incomplete += 1

            rows.append(
                {
                    **position,
                    "scanner_run_persisted": scan_present,
                    "validation_run_persisted": validation_present,
                    "execution_claim_persisted": (
                        execution_claim_present
                    ),
                    "lineage_status": (
                        "CONSISTENT"
                        if lineage_ok
                        else "LEGACY_OR_INCOMPLETE"
                    ),
                    "automatic_repair_performed": False,
                }
            )

        storage_ready = (
            str(storage.get("status") or "").lower() == "ready"
        )
        status = (
            "ready"
            if storage_ready and incomplete == 0
            else "degraded"
        )
        return {
            "status": status,
            "version": self.VERSION,
            "persistent_storage": storage,
            "latest_scanner": {
                "available": bool(scanner_payload),
                "run_id": scanner_payload.get("run_id"),
                "status": scanner_payload.get("status"),
                "universe": scanner_payload.get("universe"),
                "mode": scanner_payload.get("mode"),
            },
            "latest_validation": {
                "available": bool(validation_payload),
                "run_id": validation_payload.get("run_id"),
                "status": validation_payload.get("status"),
                "completed_at": validation_payload.get(
                    "completed_at"
                ),
            },
            "open_strategy_positions": len(rows),
            "consistent_positions": consistent,
            "incomplete_lineage_positions": incomplete,
            "positions": rows,
            "restart_safety": {
                "scanner_snapshot_persistent": bool(scanner_payload),
                "validation_snapshot_persistent": bool(
                    validation_payload
                ),
                "execution_claims_persistent": True,
                "automatic_backfill": False,
                "legacy_positions_may_require_new_scan_validation": (
                    incomplete > 0
                ),
            },
            "safety": {
                "read_only": True,
                "paper_only": True,
                "broker_orders_allowed": False,
                "repairs_or_orders_created": False,
            },
        }

    def health(self) -> dict[str, Any]:
        return self.reconciliation()


__all__ = ["StrategyRuntimeReconciliationService"]
