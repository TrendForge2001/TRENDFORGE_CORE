"""Application service for resumable NIFTY 500 scan continuations."""
from __future__ import annotations

import secrets
from typing import Any

from database.database import Database
from database.repositories.scan_continuation_repository import (
    ContinuationNotFoundError,
    ContinuationUnavailableError,
    DuplicateContinuationError,
    ScanContinuationRepository,
)


class ScanContinuationService:
    def __init__(
        self,
        repository: ScanContinuationRepository | None = None,
        db: Database | None = None,
    ) -> None:
        self._owns_database = repository is None and db is None
        self._db = db or (Database() if repository is None else None)
        self.repository = repository or ScanContinuationRepository(self._db)

    def create(
        self,
        *,
        parent_run_id: str,
        symbols: list[str],
        request: dict[str, Any],
        lineage_root_run_id: str | None = None,
        generation: int = 1,
    ) -> dict[str, Any]:
        token = secrets.token_urlsafe(24)
        return self.repository.create(
            token=token,
            parent_run_id=parent_run_id,
            lineage_root_run_id=(
                lineage_root_run_id or parent_run_id
            ),
            generation=generation,
            symbols=symbols,
            request=request,
        )

    def inspect(self, token: str) -> dict[str, Any]:
        record = self.repository.by_token(token)
        if record is None:
            raise ContinuationNotFoundError(
                "scan continuation token not found"
            )
        return record

    def claim(self, token: str, child_run_id: str) -> dict[str, Any]:
        return self.repository.claim(token, child_run_id)

    def release(self, token: str, child_run_id: str) -> dict[str, Any] | None:
        return self.repository.release(token, child_run_id)

    def consume(self, token: str, child_run_id: str) -> dict[str, Any]:
        return self.repository.consume(token, child_run_id)

    def restore_pending(
        self,
        token: str,
        child_run_id: str,
    ) -> dict[str, Any] | None:
        return self.repository.restore_pending(token, child_run_id)

    def delete_pending(self, token: str, parent_run_id: str) -> None:
        self.repository.delete_pending(token, parent_run_id)

    def health(self) -> dict[str, Any]:
        return self.repository.health()

    def close(self) -> None:
        if self._owns_database and self._db is not None:
            self._db.close()


__all__ = [
    "ContinuationNotFoundError",
    "ContinuationUnavailableError",
    "DuplicateContinuationError",
    "ScanContinuationService",
]
