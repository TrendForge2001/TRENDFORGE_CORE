"""Production scan-run audit service."""
from __future__ import annotations

from typing import Any

from database.repositories.scan_run_audit_repository import (
    ScanRunAuditRepository,
)


class ScanRunAuditService:
    def __init__(self, repository: ScanRunAuditRepository | None = None):
        self.repository = repository or ScanRunAuditRepository()

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.repository.save(payload)

    def latest(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repository.latest(limit)

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self.repository.by_run_id(run_id)


__all__ = ["ScanRunAuditService"]
