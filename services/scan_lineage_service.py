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
        if expired:
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
