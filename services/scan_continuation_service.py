"""Guarded application service for resumable NIFTY 500 scans."""
from __future__ import annotations

import secrets
from typing import Any

from database.database import Database
from database.repositories.scan_continuation_repository import (
    ContinuationAttemptLimitError,
    ContinuationExpiredError,
    ContinuationNotFoundError,
    ContinuationUnavailableError,
    DuplicateContinuationError,
    ScanContinuationRepository,
)


class ContinuationDepthExceededError(RuntimeError):
    pass


class ScanContinuationService:
    TOKEN_TTL_SECONDS = 3600
    STALE_ACTIVE_SECONDS = 1200
    MAX_GENERATION = 4
    MAX_CLAIM_ATTEMPTS = 3
    CLEANUP_RETENTION_SECONDS = 86400

    def __init__(
        self,
        repository: ScanContinuationRepository | None = None,
        db: Database | None = None,
        *,
        token_ttl_seconds: int | None = None,
        stale_active_seconds: int | None = None,
        max_generation: int | None = None,
        max_claim_attempts: int | None = None,
        cleanup_retention_seconds: int | None = None,
    ) -> None:
        self._owns_database = repository is None and db is None
        self._db = db or (Database() if repository is None else None)
        self.repository = repository or ScanContinuationRepository(self._db)

        self.token_ttl_seconds = max(
            60,
            int(
                token_ttl_seconds
                if token_ttl_seconds is not None
                else self.TOKEN_TTL_SECONDS
            ),
        )
        self.stale_active_seconds = max(
            60,
            int(
                stale_active_seconds
                if stale_active_seconds is not None
                else self.STALE_ACTIVE_SECONDS
            ),
        )
        self.max_generation = max(
            1,
            int(
                max_generation
                if max_generation is not None
                else self.MAX_GENERATION
            ),
        )
        self.max_claim_attempts = max(
            1,
            int(
                max_claim_attempts
                if max_claim_attempts is not None
                else self.MAX_CLAIM_ATTEMPTS
            ),
        )
        self.cleanup_retention_seconds = max(
            0,
            int(
                cleanup_retention_seconds
                if cleanup_retention_seconds is not None
                else self.CLEANUP_RETENTION_SECONDS
            ),
        )
        self._maintenance_totals = {
            "stale_active_recovered": 0,
            "expired_records_deleted": 0,
        }

    def maintenance(self) -> dict[str, int]:
        recovered = self.repository.recover_stale_active(
            stale_after_seconds=self.stale_active_seconds
        )
        deleted = self.repository.cleanup_expired(
            retention_seconds=self.cleanup_retention_seconds,
            stale_active_seconds=self.stale_active_seconds,
        )
        self._maintenance_totals["stale_active_recovered"] += recovered
        self._maintenance_totals["expired_records_deleted"] += deleted
        return {
            "stale_active_recovered": recovered,
            "expired_records_deleted": deleted,
        }

    def can_create_generation(self, generation: int) -> bool:
        return 1 <= int(generation) <= self.max_generation

    def create(
        self,
        *,
        parent_run_id: str,
        symbols: list[str],
        request: dict[str, Any],
        lineage_root_run_id: str | None = None,
        generation: int = 1,
    ) -> dict[str, Any]:
        self.maintenance()
        generation = int(generation)
        if not self.can_create_generation(generation):
            raise ContinuationDepthExceededError(
                "maximum continuation chain depth reached"
            )

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
            ttl_seconds=self.token_ttl_seconds,
            max_claim_attempts=self.max_claim_attempts,
        )

    def inspect(self, token: str) -> dict[str, Any]:
        self.maintenance()
        return self.repository.inspect_available(token)

    def inspect_any(self, token: str) -> dict[str, Any]:
        self.maintenance()
        record = self.repository.by_token(token)
        if record is None:
            raise ContinuationNotFoundError(
                "scan continuation token not found"
            )
        expired = self.repository._is_expired(record)
        attempts = int(record.get("claim_attempts") or 0)
        maximum = int(record.get("max_claim_attempts") or 0)
        record["expired"] = expired
        record["claim_attempts_remaining"] = max(
            0,
            maximum - attempts,
        )
        if expired:
            record["effective_status"] = "expired"
        elif (
            record.get("status") == "pending"
            and maximum > 0
            and attempts >= maximum
        ):
            record["effective_status"] = "claim_limit_exhausted"
        else:
            record["effective_status"] = record.get("status")
        return record

    def claim(self, token: str, child_run_id: str) -> dict[str, Any]:
        self.maintenance()
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
        maintenance = self.maintenance()
        payload = self.repository.health(
            stale_after_seconds=self.stale_active_seconds
        )
        payload.update(
            {
                "token_ttl_seconds": self.token_ttl_seconds,
                "stale_active_seconds": self.stale_active_seconds,
                "max_generation": self.max_generation,
                "max_claim_attempts": self.max_claim_attempts,
                "cleanup_retention_seconds": (
                    self.cleanup_retention_seconds
                ),
                "maintenance_last": maintenance,
                "maintenance_totals": dict(
                    self._maintenance_totals
                ),
            }
        )
        return payload

    def close(self) -> None:
        if self._owns_database and self._db is not None:
            self._db.close()


__all__ = [
    "ContinuationAttemptLimitError",
    "ContinuationDepthExceededError",
    "ContinuationExpiredError",
    "ContinuationNotFoundError",
    "ContinuationUnavailableError",
    "DuplicateContinuationError",
    "ScanContinuationService",
]
