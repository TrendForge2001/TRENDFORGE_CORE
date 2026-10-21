"""Background runtime for R72.5.3 multi-strategy validation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from database.repositories.strategy_runtime_state_repository import (
    StrategyRuntimeStateRepository,
)
from services.multi_strategy_validation_service import (
    MultiStrategyValidationService,
)


DEFAULT_OUTPUT_PATH = "/tmp/trendforge_r7253_validation.json"


def output_path() -> Path:
    return Path(
        os.getenv(
            "TRENDFORGE_R7253_OUTPUT_PATH",
            DEFAULT_OUTPUT_PATH,
        )
    ).expanduser()


def _persistent_validation() -> dict[str, Any] | None:
    repository = None
    try:
        repository = StrategyRuntimeStateRepository()
        row = repository.load_state(
            StrategyRuntimeStateRepository.VALIDATION_KEY
        )
        payload = row.get("payload") if isinstance(row, dict) else None
        if (
            isinstance(payload, dict)
            and payload.get("status") == "completed"
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
    app.state.r7253_validation = current
    return current


def status(app: Any) -> dict[str, Any]:
    state = _state(app)
    thread = state.get("_thread")
    current = {
        key: value
        for key, value in state.items()
        if not key.startswith("_")
    }
    current["worker_alive"] = bool(
        isinstance(thread, threading.Thread)
        and thread.is_alive()
    )
    path = output_path()
    current["output_exists"] = path.is_file()
    current["output_path"] = str(path)
    current["state_storage"] = (
        "sqlite_persistent"
        if current.get("_persistent_source") == "sqlite"
        or current.get("status") == "completed"
        else "runtime_memory"
    )
    current["restart_safe"] = bool(
        current.get("status") == "completed"
    )
    return current


def start_validation(
    app: Any,
    *,
    scanner_service: Any,
    request: dict[str, Any],
) -> dict[str, Any]:
    current = _state(app)
    thread = current.get("_thread")
    if (
        isinstance(thread, threading.Thread)
        and thread.is_alive()
    ):
        return status(app)

    payload = dict(request or {})
    force = bool(payload.pop("force", False))
    if (
        not force
        and current.get("status") == "completed"
        and current.get("request") == payload
    ):
        return status(app)

    run_id = str(
        payload.pop("run_id", "")
        or f"r7253-runtime-{uuid4().hex[:12]}"
    )
    app.state.r7253_validation = {
        "status": "running",
        "run_id": run_id,
        "request": payload,
        "progress": {
            "phase": "starting",
            "progress_pct": 0.0,
        },
    }

    def progress(update: dict[str, Any]) -> None:
        state = _state(app)
        if state.get("run_id") != run_id:
            return
        state["progress"] = dict(update)

    def worker() -> None:
        try:
            result = MultiStrategyValidationService(
                scanner_service=scanner_service,
            ).run(
                **payload,
                run_id=run_id,
                progress_callback=progress,
            )
            path = output_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(
                path.suffix + ".tmp"
            )
            temporary.write_text(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ),
                encoding="utf-8",
            )
            temporary.replace(path)
            completed_state = {
                "status": "completed",
                "run_id": run_id,
                "request": payload,
                "completed_at": result.get("completed_at"),
                "master_symbol_count": result.get(
                    "master_symbol_count"
                ),
                "strategy_count": result.get("strategy_count"),
                "error_count": len(result.get("errors") or []),
                "strategy_validation": result.get(
                    "strategy_validation"
                ),
                "strategy_universe_metrics": result.get(
                    "strategy_universe_metrics"
                ),
                "excluded_strategies": result.get(
                    "excluded_strategies"
                ),
                "progress": {
                    "phase": "completed",
                    "progress_pct": 100.0,
                },
                "output_exists": True,
                "output_path": str(path),
            }
            _persist_validation(completed_state)
            app.state.r7253_validation = completed_state
        except Exception as exc:
            app.state.r7253_validation = {
                "status": "failed",
                "run_id": run_id,
                "request": payload,
                "error": f"{type(exc).__name__}: {exc}",
                "progress": {
                    "phase": "failed",
                },
            }

    thread = threading.Thread(
        target=worker,
        name="trendforge-r7253-validation",
        daemon=True,
    )
    app.state.r7253_validation["_thread"] = thread
    thread.start()
    return status(app)


__all__ = [
    "DEFAULT_OUTPUT_PATH",
    "output_path",
    "start_validation",
    "status",
]
