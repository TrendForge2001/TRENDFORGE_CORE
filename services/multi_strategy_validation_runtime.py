"""Background runtime for R72.5.3 multi-strategy validation."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.storage_config import resolve_storage
from database.repositories.strategy_runtime_state_repository import (
    StrategyRuntimeStateRepository,
)
from scanner.strategy_registry import REGISTRY_VERSION
from services.cloud_workload_gate import validation_admission
from services.multi_strategy_validation_service import (
    MultiStrategyValidationService,
)
from services.validation_journal import ValidationJournal, write_result

DEFAULT_OUTPUT_PATH = "/tmp/trendforge_r7253_validation.json"
_START_LOCK = threading.Lock()
_LOG = logging.getLogger("trendforge.r7253")


def output_path() -> Path:
    explicit = os.getenv("TRENDFORGE_R7253_OUTPUT_PATH")
    if explicit:
        return Path(explicit).expanduser()
    if os.getenv("DATABASE_PATH") or os.getenv("TRENDFORGE_DATA_DIR"):
        return (
            resolve_storage().database.resolve().parent
            / "validation"
            / "latest_validation.json"
        )
    return Path(DEFAULT_OUTPUT_PATH)


def _persistent_validation() -> dict[str, Any] | None:
    repository = None
    try:
        repository = StrategyRuntimeStateRepository()
        row = repository.load_state(StrategyRuntimeStateRepository.VALIDATION_KEY)
        payload = row.get("payload") if isinstance(row, dict) else None
        if (
            isinstance(payload, dict)
            and payload.get("status")
            in {"completed", "running", "interrupted", "failed"}
            and payload.get("run_id")
        ):
            return {
                **payload,
                "_persistent_source": "sqlite",
            }
    except Exception:
        return None
    finally:
        if repository is not None:
            repository.close()
    return None


def _persist_validation(payload: dict[str, Any]) -> None:
    repository = StrategyRuntimeStateRepository()
    try:
        repository.save_state(
            StrategyRuntimeStateRepository.VALIDATION_KEY,
            "validation_snapshot",
            payload,
        )
        run_id = str(payload.get("run_id") or "").strip()
        if run_id:
            repository.save_state(
                f"r72.5.validation:{run_id}",
                "validation_run",
                payload,
            )
    finally:
        repository.close()


def _state(app: Any) -> dict[str, Any]:
    current = getattr(
        app.state,
        "r7253_validation",
        None,
    )
    if isinstance(current, dict):
        return current
    current = _persistent_validation() or {"status": "not_started"}
    if current.get("status") == "running" and current.get("checkpointed"):
        current["status"] = "interrupted"
        current["progress"] = {**current.get("progress", {}), "phase": "interrupted"}
    app.state.r7253_validation = current
    return current


def status(app: Any) -> dict[str, Any]:
    state = _state(app)
    thread = state.get("_thread")
    current = {key: value for key, value in state.items() if not key.startswith("_")}
    current["worker_alive"] = bool(
        isinstance(thread, threading.Thread) and thread.is_alive()
    )
    path = output_path()
    current["output_exists"] = path.is_file()
    current["output_path"] = str(path)
    current["state_storage"] = (
        "sqlite_persistent"
        if current.get("_persistent_source") == "sqlite"
        or current.get("checkpointed")
        or current.get("status") == "completed"
        else "runtime_memory"
    )
    current["restart_safe"] = bool(
        current.get("status") == "completed" or current.get("checkpointed")
    )
    current["registry_current"] = current.get("registry_version") == REGISTRY_VERSION
    current["performance_results_ready"] = (
        current.get("status") == "completed" and current["registry_current"]
    )
    return current


def _start_validation_locked(
    app: Any,
    *,
    scanner_service: Any,
    request: dict[str, Any],
) -> dict[str, Any]:
    current = _state(app)
    thread = current.get("_thread")
    if isinstance(thread, threading.Thread) and thread.is_alive():
        return status(app)

    payload = dict(request or {})
    force = bool(payload.pop("force", False))
    if (
        not force
        and current.get("status") == "completed"
        and current.get("registry_version") == REGISTRY_VERSION
        and current.get("request") == payload
    ):
        return status(app)

    supplied_id = payload.pop("run_id", "")
    resumable = (
        not force
        and current.get("status") in {"interrupted", "failed"}
        and current.get("checkpointed")
        and ValidationJournal.recent(current.get("as_of"))
        and current.get("registry_version") == REGISTRY_VERSION
        and current.get("request") == payload
    )
    run_id = str(
        supplied_id
        or (current["run_id"] if resumable else f"r7253-runtime-{uuid4().hex[:12]}")
    )
    app.state.r7253_validation = {
        "status": "running",
        "run_id": run_id,
        "request": payload,
        "registry_version": REGISTRY_VERSION,
        "checkpointed": True,
        "progress": {
            "phase": "starting",
            "progress_pct": current.get("progress", {}).get("progress_pct", 0.0)
            if resumable
            else 0.0,
        },
    }

    _persist_validation(app.state.r7253_validation)

    last_progress_log = 0.0

    def progress(update: dict[str, Any]) -> None:
        nonlocal last_progress_log
        state = _state(app)
        if state.get("run_id") != run_id:
            return
        state["progress"] = dict(update)
        count, total = (
            update.get("processed_symbol_modes"),
            update.get("total_symbol_modes"),
        )
        if isinstance(count, int) and isinstance(total, int) and total > 0:
            state["progress"].setdefault("progress_pct", round(count * 100 / total, 2))
        _persist_validation(
            {key: value for key, value in state.items() if not key.startswith("_")}
        )
        if (
            update.get("phase") == "backtest"
            and time.monotonic() - last_progress_log >= 30
        ):
            last_progress_log = time.monotonic()
            _LOG.warning(
                "validation_progress phase=running processed=%s total=%s "
                "mode=%s registry_version=%s paper_entries_changed=false",
                count,
                total,
                update.get("mode"),
                REGISTRY_VERSION,
            )

    def worker() -> None:
        checkpoint = None
        try:
            checkpoint = ValidationJournal(
                run_id, payload, REGISTRY_VERSION, fresh=force
            )
            app.state.r7253_validation["as_of"] = checkpoint.metadata["as_of"]
            _persist_validation(
                {
                    key: value
                    for key, value in app.state.r7253_validation.items()
                    if not key.startswith("_")
                }
            )
            result = MultiStrategyValidationService(
                scanner_service=scanner_service,
            ).run(
                **payload,
                run_id=run_id,
                progress_callback=progress,
                checkpoint=checkpoint,
            )
            path = output_path()
            write_result(path, result)
            completed_state = {
                "status": "completed",
                "run_id": run_id,
                "request": payload,
                "completed_at": result.get("completed_at"),
                "registry_version": result.get("registry_version"),
                "checkpointed": True,
                "as_of": result.get("as_of"),
                "master_symbol_count": result.get("master_symbol_count"),
                "strategy_count": result.get("strategy_count"),
                "error_count": len(result.get("errors") or []),
                "strategy_validation": result.get("strategy_validation"),
                "strategy_universe_metrics": result.get("strategy_universe_metrics"),
                "excluded_strategies": result.get("excluded_strategies"),
                "progress": {
                    **app.state.r7253_validation.get("progress", {}),
                    "phase": "completed",
                    "progress_pct": 100.0,
                },
                "output_exists": True,
                "output_path": str(path),
            }
            _persist_validation(completed_state)
            _LOG.warning(
                "validation_progress phase=completed processed=%s total=%s "
                "registry_version=%s paper_entries_changed=false",
                completed_state["progress"].get("processed_symbol_modes"),
                completed_state["progress"].get("total_symbol_modes"),
                REGISTRY_VERSION,
            )
            app.state.r7253_validation = {
                **app.state.r7253_validation,
                **completed_state,
            }
        except Exception:
            _LOG.exception("validation_failed run_id=%s", run_id)
            app.state.r7253_validation = {
                **app.state.r7253_validation,
                "status": "failed",
                "run_id": run_id,
                "request": payload,
                "error": (
                    "Validation failed; saved checkpoints can be resumed "
                    "using the same request"
                ),
                "progress": {
                    **app.state.r7253_validation.get("progress", {}),
                    "phase": "failed",
                },
            }
            _persist_validation(
                {
                    key: value
                    for key, value in app.state.r7253_validation.items()
                    if not key.startswith("_")
                }
            )
        finally:
            if checkpoint is not None:
                checkpoint.close()

    thread = threading.Thread(
        target=worker,
        name="trendforge-r7253-validation",
        daemon=True,
    )
    app.state.r7253_validation["_thread"] = thread
    thread.start()
    return status(app)


@validation_admission
def start_validation(
    app: Any,
    *,
    scanner_service: Any,
    request: dict[str, Any],
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    """Admit one worker per application, including concurrent HTTP requests."""
    with _START_LOCK:
        if expected_run_id is not None:
            current = _state(app)
            if (
                current.get("run_id") != expected_run_id
                or current.get("status") != "interrupted"
            ):
                return status(app)
        return _start_validation_locked(
            app,
            scanner_service=scanner_service,
            request=request,
        )


__all__ = [
    "DEFAULT_OUTPUT_PATH",
    "output_path",
    "start_validation",
    "status",
]


def start_validation_recovery(app, *, scanner_getter, session_probe):
    """Resume an already authorized historical job after authenticated startup.

    This path never starts paper entries or replays an operator Start command.
    """
    current = status(app)
    if (
        current.get("status") != "interrupted"
        or not current.get("checkpointed")
        or not current.get("registry_current")
        or not ValidationJournal.recent(current.get("as_of"))
    ):
        return None

    async def recover():
        if session_probe is not None:
            await asyncio.shield(session_probe)
        probe = getattr(app.state, "kite_session_probe", {})
        if probe.get("authenticated") is not True:
            _LOG.warning("validation_recovery phase=awaiting_authenticated_session")
            return
        try:
            result = await asyncio.to_thread(
                start_validation,
                app,
                scanner_service=scanner_getter(),
                request=current["request"],
                expected_run_id=current["run_id"],
            )
            _LOG.warning(
                "validation_recovery phase=%s paper_entries_changed=false",
                result["status"],
            )
        except Exception:
            _LOG.exception(
                "validation_recovery phase=failed paper_entries_changed=false"
            )

    return asyncio.create_task(recover(), name="validation-checkpoint-recovery")
