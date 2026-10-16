"""Pure helpers for scanner workflow presentation and continuation UX."""
from __future__ import annotations

from typing import Any


def scale_gate(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get("scale_gate")
    return value if isinstance(value, dict) else {}


def continuation_from_result(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    continuation = payload.get("continuation")
    if isinstance(continuation, dict):
        token = str(continuation.get("token") or "").strip()
        if token:
            return dict(continuation)

    gate = scale_gate(payload)
    token = str(gate.get("continuation_token") or "").strip()
    if not token:
        return None

    return {
        "token": token,
        "status": "pending",
        "generation": gate.get("next_continuation_generation"),
        "symbol_count": gate.get("continuation_symbol_count"),
        "expires_at": gate.get("next_continuation_expires_at"),
    }


def continuation_is_resumable(
    payload: dict[str, Any] | None,
) -> bool:
    if not isinstance(payload, dict):
        return False
    effective = str(
        payload.get("effective_status")
        or payload.get("status")
        or ""
    ).strip().lower()
    if effective != "pending":
        return False

    remaining = payload.get("claim_attempts_remaining")
    if remaining is None:
        return True
    try:
        return int(remaining) > 0
    except (TypeError, ValueError):
        return False


def scan_history_rows(
    payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    runs = payload.get("runs")
    if not isinstance(runs, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in runs:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        rows.append(
            {
                "Run ID": item.get("run_id"),
                "Outcome": str(
                    item.get("outcome") or "unknown"
                ).upper(),
                "Started": item.get("started_at"),
                "Duration s": item.get("duration_sec"),
                "Requested": item.get("requested_symbols"),
                "Completed": item.get("completed_symbols"),
                "Errors": item.get("error_symbols"),
                "Missing": item.get("missing_symbols"),
                "Processed": metadata.get("processed_symbols"),
                "Completion %": metadata.get(
                    "completion_pct",
                    metadata.get("accounted_pct"),
                ),
                "Budget used %": metadata.get(
                    "scan_budget_utilization_pct"
                ),
                "Continuation": bool(
                    metadata.get("is_continuation")
                ),
                "Generation": metadata.get(
                    "continuation_generation"
                ),
                "Next resume": bool(
                    metadata.get(
                        "next_continuation_available"
                    )
                ),
            }
        )
    return rows


def lineage_run_rows(
    payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    attempts = payload.get("attempt_runs")
    runs = attempts if isinstance(attempts, list) else []
    if not runs:
        committed = payload.get("committed_runs")
        runs = committed if isinstance(committed, list) else []

    rows: list[dict[str, Any]] = []
    for item in runs:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        rows.append(
            {
                "Run ID": item.get("run_id"),
                "Outcome": str(
                    item.get("outcome") or "unknown"
                ).upper(),
                "Requested": item.get("requested_symbols"),
                "Completed": item.get("completed_symbols"),
                "Errors": item.get("error_symbols"),
                "Duration s": item.get("duration_sec"),
                "Continuation": bool(
                    metadata.get("is_continuation")
                ),
                "Parent": metadata.get("parent_run_id"),
                "Generation": metadata.get(
                    "continuation_generation"
                ),
            }
        )
    return rows
