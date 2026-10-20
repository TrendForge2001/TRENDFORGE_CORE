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


def fundamental_gap_rows(
    payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Identify actionable fundamental data gaps without altering scan gates.

    Compact R65+ payloads expose every requested symbol under symbol_results.
    Noncompact responses preserve analysis_ranked and rejected partitions.
    """
    if not isinstance(payload, dict):
        return []

    compact = payload.get("symbol_results")
    if isinstance(compact, list):
        candidates = compact
    else:
        candidates = []
        for key in ("analysis_ranked", "analysis_rejected", "execution_rejected", "results", "rejected"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(value)

    gaps: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        readiness = item.get("fundamental_readiness")
        if not symbol or not isinstance(readiness, dict):
            continue
        status = str(readiness.get("status") or "").strip().upper()
        if status not in {"DATA_INCOMPLETE", "MISSING", "INVALID", "STALE"}:
            continue
        missing = readiness.get("missing_fields")
        invalid = readiness.get("invalid_fields")
        missing = missing if isinstance(missing, (list, tuple)) else []
        invalid = invalid if isinstance(invalid, (list, tuple)) else []
        row = {
            "Symbol": symbol,
            "Readiness": status,
            "Missing fields": ", ".join(str(x) for x in missing),
            "Invalid fields": ", ".join(str(x) for x in invalid),
            "Execution block": str(item.get("primary_execution_block") or ""),
        }
        # A repeated symbol from another result partition may contain
        # richer diagnostics; prefer that row without duplicating it.
        prior = gaps.get(symbol)
        if prior is None or len(row["Missing fields"]) + len(row["Invalid fields"]) > len(prior["Missing fields"]) + len(prior["Invalid fields"]):
            gaps[symbol] = row
    return [gaps[symbol] for symbol in sorted(gaps)]


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
    source = "attempt"
    if not runs:
        committed = payload.get("committed_runs")
        runs = committed if isinstance(committed, list) else []
        source = "committed"

    rows: list[dict[str, Any]] = []
    for item in runs:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "Run ID": item.get("run_id"),
                "Outcome": str(
                    item.get("outcome") or "unknown"
                ).upper(),
                "HTTP": item.get("http_status"),
                "Failure stage": item.get("failure_stage"),
                "Requested": item.get("requested_symbols"),
                "Completed": item.get("completed_symbols"),
                "Processed": item.get("processed_symbols"),
                "Duration s": item.get("duration_sec"),
                "SLA": item.get("sla_status"),
                "View": source,
            }
        )
    return rows
