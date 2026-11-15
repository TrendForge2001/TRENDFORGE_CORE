"""Bounded diagnostics: no exception messages, provider bodies or credentials."""

import hashlib
import json
import re
from pathlib import Path


class ResearchInputUnavailable(ValueError):
    """A research request has no usable observations."""


def failure_diagnostic(error, phase="unknown"):
    from providers.market_data_provider import ProviderAuthenticationError
    from services.execution_report import ReportValidationError
    from services.research_capacity import ResearchCapacityExceeded

    code = (
        "research_kite_authentication_failed"
        if isinstance(error, ProviderAuthenticationError)
        else "research_row_budget_exceeded"
        if isinstance(error, ResearchCapacityExceeded)
        else "report_evidence_invalid"
        if isinstance(error, ReportValidationError)
        else "research_history_unavailable"
        if isinstance(error, ResearchInputUnavailable)
        else "research_batch_failed"
    )
    root = Path(__file__).resolve().parents[1]
    frames = []
    trace = error.__traceback__
    while trace is not None:
        try:
            path = Path(trace.tb_frame.f_code.co_filename).resolve().relative_to(root)
            if re.fullmatch(r"[A-Za-z0-9_./-]+", str(path)):
                frames.append({"file": str(path), "line": trace.tb_lineno})
        except ValueError:
            pass
        trace = trace.tb_next
    name = type(error).__name__
    name = name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name) else "Exception"
    payload = {
        "code": code,
        "error_type": name,
        "frames": frames[-8:],
        "phase": phase
        if phase in {"starting", "history", "simulation", "report", "unknown"}
        else "unknown",
    }
    from providers.kite_diagnostics import MESSAGES

    session_code = getattr(error, "diagnostic_code", None)
    if (
        isinstance(error, ProviderAuthenticationError)
        and isinstance(session_code, str)
        and session_code in MESSAGES
    ):
        payload["session_code"] = session_code
    payload["reference"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()[:12]
    return payload


def fail_research(repository, batch_id, error):
    batch = repository.get(batch_id) or {}
    diagnostic = failure_diagnostic(error, batch.get("phase", "unknown"))
    repository.fail(batch_id, diagnostic["code"], diagnostic=diagnostic)
    return diagnostic


def failure_message(code):
    return {
        "research_kite_authentication_failed": (
            "Kite session verification failed. Check Live Kite Session for the "
            "authentication or network reason, then retry this backtest."
        ),
        "research_history_unavailable": (
            "No usable stock history was returned. Check Kite history access "
            "and stock data readiness."
        ),
        "research_row_budget_exceeded": (
            "The observed history exceeded this worker's candle budget. "
            "Use a smaller universe or the PC runtime."
        ),
        "report_evidence_invalid": (
            "The engine's account or trade evidence did not reconcile. "
            "The run has stopped without publishing a report."
        ),
        "research_batch_failed": (
            "The backtest engine failed. The saved diagnostic reference "
            "identifies the failing code path."
        ),
    }.get(code)
