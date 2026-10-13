"""Production scan-run audit service."""
from __future__ import annotations

from typing import Any

from database.repositories.scan_run_audit_repository import (
    DuplicateScanRunIdError,
    ScanRunAuditRepository,
)


class ScanRunAuditService:
    def __init__(self, repository: ScanRunAuditRepository | None = None):
        self.repository = repository or ScanRunAuditRepository()

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.repository.save(payload)

    def ensure_available(self, run_id: str) -> None:
        run_id = str(run_id or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        if self.repository.exists(run_id):
            raise DuplicateScanRunIdError(
                f"scan run_id already exists: {run_id}"
            )

    def exists(self, run_id: str) -> bool:
        return self.repository.exists(run_id)

    def latest(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repository.latest(limit)

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self.repository.by_run_id(run_id)

    def health(self) -> dict[str, Any]:
        method = getattr(self.repository, "health", None)
        if callable(method):
            payload = method()
            return payload if isinstance(payload, dict) else {
                "status": "unknown"
            }
        return {
            "status": "configured",
            "storage": "sqlite",
            "database_path": self.repository.db.db_path,
        }


__all__ = [
    "DuplicateScanRunIdError",
    "ScanRunAuditService",
]
