"""Background runtime wrapper for R71.5 universe validation."""
from __future__ import annotations

import base64
import gzip
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from services.technical_validation_service import TechnicalValidationService


LOGGER = logging.getLogger("trendforge.r715")
DEFAULT_OUTPUT_PATH = "/tmp/trendforge_r715_validation.json"
LOG_EXPORT_CHUNK_SIZE = 12_000
_START_LOCK = threading.Lock()


def _log_export_payload(result: dict[str, Any]) -> None:
    if not _enabled("TRENDFORGE_R715_LOG_EXPORT", False):
        return
    raw = json.dumps(
        result,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    encoded = base64.b64encode(gzip.compress(raw, compresslevel=9)).decode("ascii")
    total = max(1, (len(encoded) + LOG_EXPORT_CHUNK_SIZE - 1) // LOG_EXPORT_CHUNK_SIZE)
    LOGGER.warning(
        "R715_EXPORT_BEGIN encoding=gzip+base64 chunks=%s bytes=%s",
        total,
        len(raw),
    )
    for index in range(total):
        chunk = encoded[
            index * LOG_EXPORT_CHUNK_SIZE : (index + 1) * LOG_EXPORT_CHUNK_SIZE
        ]
        LOGGER.warning(
            "R715_EXPORT_CHUNK %s/%s %s",
            index + 1,
            total,
            chunk,
        )
    LOGGER.warning("R715_EXPORT_END chunks=%s", total)


def _enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def output_path() -> Path:
    return Path(
        os.getenv("TRENDFORGE_R715_OUTPUT_PATH", DEFAULT_OUTPUT_PATH)
    ).expanduser()


def _state(app: Any) -> dict[str, Any]:
    current = getattr(app.state, "r715_validation", None)
    if isinstance(current, dict):
        return current
    current = {"status": "not_started"}
    app.state.r715_validation = current
    return current


def status(app: Any) -> dict[str, Any]:
    """Expose only public, JSON-serializable runtime state."""
    state = _state(app)
    thread = state.get("_thread")
    current = {
        key: value
        for key, value in state.items()
        if not key.startswith("_")
    }
    current["worker_alive"] = (
        isinstance(thread, threading.Thread) and thread.is_alive()
    )
    path = output_path()
    current["output_exists"] = path.is_file()
    current["output_path"] = str(path)
    return current


def _start_validation_locked(
    app: Any,
    *,
    technical_service: Any,
    capital: float | None = None,
    chunk_size: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    current = _state(app)
    thread = current.get("_thread")
    if (
        isinstance(thread, threading.Thread)
        and thread.is_alive()
    ):
        return {
            key: value
            for key, value in current.items()
            if not key.startswith("_")
        }

    run_id = f"r715-runtime-{uuid4().hex[:12]}"
    run_capital = float(
        capital
        if capital is not None
        else os.getenv("TRENDFORGE_R715_CAPITAL", "100000")
    )
    run_chunk_size = int(
        chunk_size
        if chunk_size is not None
        else os.getenv("TRENDFORGE_R715_CHUNK_SIZE", "25")
    )
    app.state.r715_validation = {
        "status": "running",
        "run_id": run_id,
        "started": True,
        "capital": run_capital,
        "chunk_size": run_chunk_size,
    }

    def worker() -> None:
        try:
            result = TechnicalValidationService(
                technical_service=technical_service
            ).run(
                capital=run_capital,
                chunk_size=run_chunk_size,
                force_refresh_universes=True,
                run_id=run_id,
            )
            path = output_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + f".{run_id}.tmp")
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
            _log_export_payload(result)
            app.state.r715_validation = {
                **app.state.r715_validation,
                "status": "completed",
                "run_id": run_id,
                "completed_at": result.get("completed_at"),
                "master_symbol_count": result.get("master_symbol_count"),
                "aggregate": result.get("aggregate"),
                "error_count": len(result.get("errors") or []),
                "output_path": str(path),
                "output_exists": True,
            }
            LOGGER.warning(
                "R715_VALIDATION_COMPLETED run_id=%s symbols=%s errors=%s path=%s",
                run_id,
                result.get("master_symbol_count"),
                len(result.get("errors") or []),
                path,
            )
        except Exception:
            app.state.r715_validation = {
                **app.state.r715_validation,
                "status": "failed",
                "run_id": run_id,
                "error": "Validation failed; consult the server log using the run ID",
            }
            LOGGER.exception("R715_VALIDATION_FAILED run_id=%s", run_id)

    thread = threading.Thread(
        target=worker,
        name="trendforge-r715-validation",
        daemon=True,
    )
    app.state.r715_validation["_thread"] = thread
    thread.start()
    return {
        key: value
        for key, value in app.state.r715_validation.items()
        if not key.startswith("_")
    }


def start_validation(
    app: Any,
    *,
    technical_service: Any,
    capital: float | None = None,
    chunk_size: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Serialize admission; force never starts a second active worker."""
    with _START_LOCK:
        return _start_validation_locked(
            app, technical_service=technical_service,
            capital=capital, chunk_size=chunk_size, force=force,
        )


def start_if_configured(app: Any, *, technical_service: Any) -> dict[str, Any]:
    if not _enabled("TRENDFORGE_R715_VALIDATION_RUN_ON_START", False):
        state = _state(app)
        state.setdefault("status", "disabled")
        return status(app)
    return start_validation(
        app,
        technical_service=technical_service,
        force=False,
    )


__all__ = [
    "DEFAULT_OUTPUT_PATH",
    "output_path",
    "start_if_configured",
    "start_validation",
    "status",
]
