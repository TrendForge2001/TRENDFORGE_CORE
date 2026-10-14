"""End-to-end rollup for resumable NIFTY 500 scan lineages."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class ScanLineageNotFoundError(LookupError):
    pass


class ScanLineageService:
    def __init__(self, audit_service, continuation_service):
        self.audit_service = audit_service
        self.continuation_service = continuation_service

    @staticmethod
    def _pct(value: int, total: int) -> float:
        if total <= 0:
            return 100.0
        return round(min(100.0, max(0.0, value / total * 100.0)), 2)

    @staticmethod
    def _parse(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _resolve_root(self, run_id: str) -> tuple[str, dict[str, Any]]:
        record = self.audit_service.get(run_id)
        if record is None:
            raise ScanLineageNotFoundError("scan run not found")
        metadata = dict(record.get("metadata") or {})
        root = str(
            metadata.get("lineage_root_run_id")
            or record.get("run_id")
            or run_id
        ).strip()
        root_record = self.audit_service.get(root)
        if root_record is None:
            raise ScanLineageNotFoundError("scan lineage root not found")
        return root, root_record

    def _decorate_continuation(
        self,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        attempts = int(record.get("claim_attempts") or 0)
        maximum = int(record.get("max_claim_attempts") or 0)
        expires = self._parse(record.get("expires_at"))
        now = datetime.now(timezone.utc)
        expired = bool(expires is not None and expires <= now)
        status = str(record.get("status") or "unknown")
        effective = status
        if status == "pending" and expired:
            effective = "expired"
        elif status == "pending" and maximum > 0 and attempts >= maximum:
            effective = "claim_limit_exhausted"

        return {
            "parent_run_id": record.get("parent_run_id"),
            "child_run_id": record.get("child_run_id"),
            "generation": int(record.get("generation") or 0),
            "status": status,
            "effective_status": effective,
            "symbol_count": len(record.get("symbols") or []),
            "created_at": record.get("created_at"),
            "claimed_at": record.get("claimed_at"),
            "consumed_at": record.get("consumed_at"),
            "expires_at": record.get("expires_at"),
            "claim_attempts": attempts,
            "max_claim_attempts": maximum,
            "claim_attempts_remaining": max(0, maximum - attempts),
            "recovery_count": int(record.get("recovery_count") or 0),
        }

    @staticmethod
    def _metadata(record: dict[str, Any]) -> dict[str, Any]:
        metadata = record.get("metadata")
        return metadata if isinstance(metadata, dict) else {}

    def _integrity(
        self,
        *,
        root_run_id: str,
        root_audit: dict[str, Any],
        audits: list[dict[str, Any]],
        raw_continuations: list[dict[str, Any]],
        committed: list[dict[str, Any]],
    ) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []

        def issue(
            code: str,
            severity: str,
            message: str,
            **context: Any,
        ) -> None:
            payload = {
                "code": code,
                "severity": severity,
                "message": message,
            }
            payload.update(
                {
                    key: value
                    for key, value in context.items()
                    if value is not None
                }
            )
            issues.append(payload)

        audit_by_id = {
            str(item.get("run_id") or "").strip(): item
            for item in audits
            if str(item.get("run_id") or "").strip()
        }
        root_metadata = self._metadata(root_audit)
        declared_root = str(
            root_metadata.get("lineage_root_run_id") or ""
        ).strip()
        if declared_root and declared_root != root_run_id:
            issue(
                "ROOT_METADATA_MISMATCH",
                "error",
                "Root audit declares a different lineage root",
                run_id=root_run_id,
                declared_root_run_id=declared_root,
            )

        executable = [
            item
            for item in raw_continuations
            if str(item.get("status")) in {"pending", "active"}
        ]
        if len(executable) > 1:
            issue(
                "MULTIPLE_EXECUTABLE_CONTINUATIONS",
                "error",
                "More than one continuation is executable in one lineage",
                count=len(executable),
            )

        generations = [
            int(item.get("generation") or 0)
            for item in raw_continuations
            if int(item.get("generation") or 0) > 0
        ]
        if len(generations) != len(set(generations)):
            issue(
                "DUPLICATE_CONTINUATION_GENERATION",
                "error",
                "Continuation generations are not unique",
                generations=sorted(generations),
            )
        if generations:
            unique = sorted(set(generations))
            expected = list(range(1, max(unique) + 1))
            if unique != expected:
                issue(
                    "CONTINUATION_GENERATION_HISTORY_GAP",
                    "warning",
                    "Continuation history has generation gaps; older rows may have been cleaned",
                    generations=unique,
                    expected_generations=expected,
                )

        continuation_keys = {
            (
                str(item.get("parent_run_id") or "").strip(),
                int(item.get("generation") or 0),
            )
            for item in raw_continuations
        }

        for continuation in raw_continuations:
            parent_run_id = str(
                continuation.get("parent_run_id") or ""
            ).strip()
            lineage_root = str(
                continuation.get("lineage_root_run_id") or ""
            ).strip()
            generation = int(continuation.get("generation") or 0)
            status = str(continuation.get("status") or "")
            child_run_id = str(
                continuation.get("child_run_id") or ""
            ).strip()

            if lineage_root != root_run_id:
                issue(
                    "CONTINUATION_ROOT_MISMATCH",
                    "error",
                    "Continuation points at a different lineage root",
                    parent_run_id=parent_run_id,
                    generation=generation,
                    declared_root_run_id=lineage_root,
                )

            parent = (
                audit_by_id.get(parent_run_id)
                or self.audit_service.get(parent_run_id)
            )
            if parent is None:
                issue(
                    "CONTINUATION_PARENT_AUDIT_MISSING",
                    "error",
                    "Continuation parent audit does not exist",
                    parent_run_id=parent_run_id,
                    generation=generation,
                )
            else:
                parent_metadata = self._metadata(parent)
                parent_root = str(
                    parent_metadata.get("lineage_root_run_id")
                    or parent.get("run_id")
                    or ""
                ).strip()
                if parent_root != root_run_id:
                    issue(
                        "CONTINUATION_PARENT_ROOT_MISMATCH",
                        "error",
                        "Continuation parent audit belongs to another lineage",
                        parent_run_id=parent_run_id,
                        generation=generation,
                        parent_root_run_id=parent_root,
                    )

                parent_generation = parent_metadata.get(
                    "continuation_generation"
                )
                if parent_generation is not None:
                    try:
                        parent_generation = int(parent_generation)
                    except (TypeError, ValueError):
                        parent_generation = None
                    if (
                        parent_generation is not None
                        and generation > 0
                        and parent_generation != generation - 1
                    ):
                        issue(
                            "CONTINUATION_PARENT_GENERATION_MISMATCH",
                            "error",
                            "Continuation generation does not follow its parent audit generation",
                            parent_run_id=parent_run_id,
                            generation=generation,
                            parent_generation=parent_generation,
                        )

                deferred = [
                    str(symbol).strip().upper()
                    for symbol in (
                        parent_metadata.get("deferred_symbols") or []
                    )
                    if str(symbol).strip()
                ]
                continuation_symbols = [
                    str(symbol).strip().upper()
                    for symbol in (
                        continuation.get("symbols") or []
                    )
                    if str(symbol).strip()
                ]
                if deferred and deferred != continuation_symbols:
                    issue(
                        "CONTINUATION_DEFERRED_SYMBOL_MISMATCH",
                        "error",
                        "Persisted continuation symbols differ from the parent deferred-symbol set",
                        parent_run_id=parent_run_id,
                        generation=generation,
                        parent_deferred_count=len(deferred),
                        continuation_symbol_count=len(
                            continuation_symbols
                        ),
                    )

            if generation < 1:
                issue(
                    "CONTINUATION_GENERATION_INVALID",
                    "error",
                    "Continuation generation must be at least 1",
                    parent_run_id=parent_run_id,
                    generation=generation,
                )

            if status == "pending" and child_run_id:
                issue(
                    "PENDING_CONTINUATION_HAS_CHILD",
                    "error",
                    "Pending continuation unexpectedly retains a child run",
                    parent_run_id=parent_run_id,
                    child_run_id=child_run_id,
                    generation=generation,
                )
            elif status == "active" and not child_run_id:
                issue(
                    "ACTIVE_CONTINUATION_MISSING_CHILD",
                    "error",
                    "Active continuation has no claimed child run",
                    parent_run_id=parent_run_id,
                    generation=generation,
                )
            elif status == "consumed":
                if not child_run_id:
                    issue(
                        "CONSUMED_CONTINUATION_MISSING_CHILD",
                        "error",
                        "Consumed continuation has no committed child run",
                        parent_run_id=parent_run_id,
                        generation=generation,
                    )
                    continue

                child = (
                    audit_by_id.get(child_run_id)
                    or self.audit_service.get(child_run_id)
                )
                if child is None:
                    issue(
                        "CONSUMED_CHILD_AUDIT_MISSING",
                        "error",
                        "Consumed continuation child audit does not exist",
                        parent_run_id=parent_run_id,
                        child_run_id=child_run_id,
                        generation=generation,
                    )
                    continue

                child_metadata = self._metadata(child)
                child_root = str(
                    child_metadata.get("lineage_root_run_id") or ""
                ).strip()
                if child_root != root_run_id:
                    issue(
                        "CONSUMED_CHILD_ROOT_MISMATCH",
                        "error",
                        "Committed child audit declares the wrong lineage root",
                        child_run_id=child_run_id,
                        generation=generation,
                        child_root_run_id=child_root,
                    )
                if str(
                    child_metadata.get("parent_run_id") or ""
                ).strip() != parent_run_id:
                    issue(
                        "CONSUMED_CHILD_PARENT_MISMATCH",
                        "error",
                        "Committed child audit declares the wrong parent run",
                        parent_run_id=parent_run_id,
                        child_run_id=child_run_id,
                        generation=generation,
                    )
                try:
                    child_generation = int(
                        child_metadata.get(
                            "continuation_generation"
                        )
                    )
                except (TypeError, ValueError):
                    child_generation = -1
                if child_generation != generation:
                    issue(
                        "CONSUMED_CHILD_GENERATION_MISMATCH",
                        "error",
                        "Committed child audit generation differs from continuation generation",
                        child_run_id=child_run_id,
                        generation=generation,
                        child_generation=child_generation,
                    )
                if str(child.get("outcome")) not in {
                    "completed",
                    "partial",
                }:
                    issue(
                        "CONSUMED_CHILD_OUTCOME_INVALID",
                        "error",
                        "Consumed continuation points to a non-committed child outcome",
                        child_run_id=child_run_id,
                        generation=generation,
                        child_outcome=child.get("outcome"),
                    )
                requested = int(
                    child.get("requested_symbols") or 0
                )
                symbol_count = len(
                    continuation.get("symbols") or []
                )
                if requested != symbol_count:
                    issue(
                        "CONSUMED_CHILD_REQUEST_COUNT_MISMATCH",
                        "error",
                        "Committed child requested-symbol count differs from continuation symbol count",
                        child_run_id=child_run_id,
                        generation=generation,
                        requested_symbols=requested,
                        continuation_symbol_count=symbol_count,
                    )

        for audit in audits:
            metadata = self._metadata(audit)
            if not bool(metadata.get("is_continuation")):
                continue
            run_id = str(audit.get("run_id") or "").strip()
            parent_run_id = str(
                metadata.get("parent_run_id") or ""
            ).strip()
            generation_raw = metadata.get(
                "continuation_generation"
            )
            try:
                generation = int(generation_raw)
            except (TypeError, ValueError):
                generation = -1

            if not parent_run_id:
                issue(
                    "CONTINUATION_AUDIT_PARENT_MISSING",
                    "error",
                    "Continuation attempt audit has no parent run ID",
                    run_id=run_id,
                    generation=generation,
                )
                continue
            parent = (
                audit_by_id.get(parent_run_id)
                or self.audit_service.get(parent_run_id)
            )
            if parent is None:
                issue(
                    "CONTINUATION_AUDIT_PARENT_NOT_FOUND",
                    "error",
                    "Continuation attempt audit references a missing parent audit",
                    run_id=run_id,
                    parent_run_id=parent_run_id,
                    generation=generation,
                )

            if generation < 1:
                issue(
                    "CONTINUATION_AUDIT_GENERATION_INVALID",
                    "error",
                    "Continuation attempt audit has an invalid generation",
                    run_id=run_id,
                    parent_run_id=parent_run_id,
                    generation=generation,
                )
            elif (
                parent_run_id,
                generation,
            ) not in continuation_keys:
                issue(
                    "CONTINUATION_RECORD_ABSENT",
                    "warning",
                    "Audit references continuation history no longer present; it may have been cleaned by retention policy",
                    run_id=run_id,
                    parent_run_id=parent_run_id,
                    generation=generation,
                    outcome=audit.get("outcome"),
                )

        root_requested = int(
            root_audit.get("requested_symbols") or 0
        )
        committed_completed = sum(
            int(item.get("completed_symbols") or 0)
            for item in committed
        )
        committed_processed = sum(
            int(
                self._metadata(item).get(
                    "processed_symbols",
                    0,
                )
                or 0
            )
            for item in committed
        )
        if (
            root_requested > 0
            and committed_completed > root_requested
        ):
            issue(
                "COMMITTED_COMPLETION_OVERFLOW",
                "error",
                "Committed completion exceeds the root requested universe",
                root_requested_symbols=root_requested,
                cumulative_completed_symbols=committed_completed,
            )
        if (
            root_requested > 0
            and committed_processed > root_requested
        ):
            issue(
                "COMMITTED_PROCESSED_OVERFLOW",
                "error",
                "Committed processed count exceeds the root requested universe",
                root_requested_symbols=root_requested,
                cumulative_processed_symbols=committed_processed,
            )

        error_count = sum(
            1
            for item in issues
            if item["severity"] == "error"
        )
        warning_count = sum(
            1
            for item in issues
            if item["severity"] == "warning"
        )
        status = (
            "unhealthy"
            if error_count
            else "warning"
            if warning_count
            else "healthy"
        )
        return {
            "status": status,
            "valid": error_count == 0,
            "issue_count": len(issues),
            "error_count": error_count,
            "warning_count": warning_count,
            "audit_record_count": len(audits),
            "continuation_record_count": len(raw_continuations),
            "executable_continuation_count": len(executable),
            "issues": issues,
        }

    def rollup(self, run_id: str) -> dict[str, Any]:
        requested_run = str(run_id or "").strip()
        if not requested_run:
            raise ValueError("run_id is required")

        root_run_id, root_audit = self._resolve_root(requested_run)
        audits = list(self.audit_service.lineage(root_run_id))
        raw_continuations = list(
            self.continuation_service.lineage(root_run_id)
        )
        continuations = [
            self._decorate_continuation(record)
            for record in raw_continuations
        ]

        committed_ids = {root_run_id}
        for record in raw_continuations:
            parent = str(record.get("parent_run_id") or "").strip()
            if parent:
                committed_ids.add(parent)
            if str(record.get("status")) == "consumed":
                child = str(record.get("child_run_id") or "").strip()
                if child:
                    committed_ids.add(child)

        # Immutable successful continuation audits are sufficient to
        # reconstruct the historical committed path after R66.9 cleanup
        # removes old consumed continuation rows.
        for audit in audits:
            metadata = self._metadata(audit)
            if (
                bool(metadata.get("is_continuation"))
                and str(audit.get("outcome"))
                in {"completed", "partial"}
            ):
                audit_run_id = str(
                    audit.get("run_id") or ""
                ).strip()
                if audit_run_id:
                    committed_ids.add(audit_run_id)

        audit_by_id = {
            str(item.get("run_id")): item
            for item in audits
            if item.get("run_id")
        }
        committed = [
            audit_by_id[run]
            for run in committed_ids
            if run in audit_by_id
        ]
        committed.sort(key=lambda item: int(item.get("id") or 0))
        attempts = sorted(
            audits,
            key=lambda item: int(item.get("id") or 0),
        )

        root_requested = int(root_audit.get("requested_symbols") or 0)
        cumulative_completed = sum(
            int(item.get("completed_symbols") or 0)
            for item in committed
        )
        cumulative_processed = sum(
            int((item.get("metadata") or {}).get("processed_symbols") or 0)
            for item in committed
        )
        cumulative_duration = round(
            sum(float(item.get("duration_sec") or 0.0) for item in committed),
            3,
        )
        remaining = max(0, root_requested - cumulative_completed)

        latest = committed[-1] if committed else root_audit
        latest_metadata = dict(latest.get("metadata") or {})
        effective_states = [
            item["effective_status"] for item in continuations
        ]

        if "active" in effective_states:
            status = "in_progress"
        elif any(
            state in {"expired", "claim_limit_exhausted"}
            for state in effective_states
        ):
            status = "blocked"
        elif "pending" in effective_states:
            status = "resumable"
        elif str(latest.get("outcome")) == "completed" and remaining == 0:
            status = "completed"
        elif latest_metadata.get("continuation_limit_reason"):
            status = "blocked"
        elif str(latest.get("outcome")) == "failed":
            status = "failed"
        elif str(latest.get("outcome")) == "rejected":
            status = "rejected"
        else:
            status = "partial"

        sla_values = [
            (item.get("metadata") or {}).get("sla_met")
            for item in committed
            if "sla_met" in (item.get("metadata") or {})
        ]
        if any(value is False for value in sla_values):
            lineage_sla_status = "breached"
        elif sla_values and all(value is True for value in sla_values):
            lineage_sla_status = "met"
        else:
            lineage_sla_status = "unknown"

        start = self._parse(root_audit.get("started_at"))
        finish_candidates = [
            self._parse(item.get("finished_at"))
            for item in committed
        ]
        finish_candidates = [
            item for item in finish_candidates if item is not None
        ]
        end_to_end_elapsed = (
            round((max(finish_candidates) - start).total_seconds(), 3)
            if start is not None and finish_candidates
            else None
        )

        integrity = self._integrity(
            root_run_id=root_run_id,
            root_audit=root_audit,
            audits=audits,
            raw_continuations=raw_continuations,
            committed=committed,
        )

        return {
            "requested_run_id": requested_run,
            "lineage_root_run_id": root_run_id,
            "status": status,
            "terminal": status in {
                "completed",
                "blocked",
                "failed",
                "rejected",
            },
            "root_requested_symbols": root_requested,
            "cumulative_completed_symbols": cumulative_completed,
            "cumulative_processed_symbols": cumulative_processed,
            "remaining_symbols": remaining,
            "end_to_end_completion_pct": self._pct(
                cumulative_completed,
                root_requested,
            ),
            "end_to_end_processed_pct": self._pct(
                cumulative_processed,
                root_requested,
            ),
            "committed_run_count": len(committed),
            "attempt_run_count": len(attempts),
            "continuation_count": len(continuations),
            "latest_committed_run_id": latest.get("run_id"),
            "latest_committed_outcome": latest.get("outcome"),
            "cumulative_scan_duration_sec": cumulative_duration,
            "end_to_end_elapsed_sec": end_to_end_elapsed,
            "lineage_sla_status": lineage_sla_status,
            "integrity_status": integrity["status"],
            "integrity_issue_count": integrity["issue_count"],
            "integrity": integrity,
            "fallback_count": sum(
                int(item.get("fallback_count") or 0)
                for item in committed
            ),
            "nse_resolution_count": sum(
                int(item.get("nse_resolution_count") or 0)
                for item in committed
            ),
            "committed_runs": [
                {
                    "run_id": item.get("run_id"),
                    "outcome": item.get("outcome"),
                    "requested_symbols": item.get("requested_symbols"),
                    "completed_symbols": item.get("completed_symbols"),
                    "processed_symbols": (
                        item.get("metadata") or {}
                    ).get("processed_symbols"),
                    "duration_sec": item.get("duration_sec"),
                    "sla_status": (
                        item.get("metadata") or {}
                    ).get("sla_status"),
                }
                for item in committed
            ],
            "attempt_runs": [
                {
                    "run_id": item.get("run_id"),
                    "outcome": item.get("outcome"),
                    "failure_stage": item.get("failure_stage"),
                    "http_status": item.get("http_status"),
                }
                for item in attempts
            ],
            "continuations": continuations,
        }


__all__ = [
    "ScanLineageNotFoundError",
    "ScanLineageService",
]
