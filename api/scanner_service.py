"""Application-facing scanner service using the canonical full pipeline."""
from __future__ import annotations

import threading
import time
from typing import Any

from scanner.full_pipeline import FullScannerPipeline


class ScannerService:
    """Thin application boundary; execution remains owned by the canonical pipeline."""

    def __init__(self, pipeline: FullScannerPipeline):
        if pipeline is None:
            raise ValueError("A FullScannerPipeline is required")
        self.pipeline = pipeline
        self._runtime_lock = threading.Lock()
        self._runtime_status = "not_probed"
        self._last_success_at: float | None = None
        self._last_failure_at: float | None = None
        self._last_error: str | None = None

    def _mark_runtime_success(self) -> None:
        with self._runtime_lock:
            self._runtime_status = "runtime_verified"
            self._last_success_at = time.time()
            self._last_error = None

    def _mark_runtime_failure(self, exc: Exception | str) -> None:
        with self._runtime_lock:
            self._runtime_status = "failed"
            self._last_failure_at = time.time()
            self._last_error = str(exc)

    @staticmethod
    def _batch_has_runtime_success(result: Any) -> bool:
        if not isinstance(result, dict):
            return False

        items: list[dict[str, Any]] = []
        for key in ("results", "rejected", "eligible"):
            value = result.get(key)
            if isinstance(value, list):
                items.extend(
                    item for item in value
                    if isinstance(item, dict)
                )

        if items:
            return any(not item.get("error") for item in items)

        try:
            return int(result.get("scanned_count", 0) or 0) > 0
        except (TypeError, ValueError):
            return False

    def scan(self, symbol: str, *, period: str = "6mo", interval: str = "1d",
             capital: float = 0.0, fundamentals: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            result = self.pipeline.analyze(
                symbol,
                period=period,
                interval=interval,
                capital=capital,
                fundamentals=fundamentals,
            )
        except Exception as exc:
            self._mark_runtime_failure(exc)
            raise

        if isinstance(result, dict) and not result.get("error"):
            self._mark_runtime_success()
        else:
            self._mark_runtime_failure(
                "Scanner returned no successful runtime result"
            )
        return result

    def scan_many(self, symbols: list[str], *, period: str = "6mo", interval: str = "1d",
                  capital: float = 0.0, top_n: int = 20) -> dict[str, Any]:
        try:
            result = self.pipeline.analyze_many(
                symbols,
                period=period,
                interval=interval,
                capital=capital,
                top_n=top_n,
            )
        except Exception as exc:
            self._mark_runtime_failure(exc)
            raise

        if self._batch_has_runtime_success(result):
            self._mark_runtime_success()
        else:
            self._mark_runtime_failure(
                "Batch scan produced no successful symbol results"
            )
        return result

    def health(self) -> dict[str, Any]:
        orchestrator = getattr(self.pipeline, "orchestrator", None)
        health = orchestrator.health() if callable(getattr(orchestrator, "health", None)) else {"status": "unknown"}
        orchestrator_status = str(health.get("status", "unknown")).lower() if isinstance(health, dict) else "unknown"
        status_map = {
            "healthy": "healthy",
            "ok": "healthy",
            "configured": "configured",
            "degraded": "degraded",
            "unavailable": "degraded",
        }
        configured_status = status_map.get(
            orchestrator_status,
            "degraded",
        )
        if configured_status == "degraded":
            status = "degraded"
        elif self._runtime_status == "runtime_verified":
            status = "healthy"
        elif self._runtime_status == "failed":
            status = "degraded"
        else:
            status = configured_status

        return {
            "status": status,
            "pipeline": self.pipeline.__class__.__name__,
            "orchestrator": health,
            "runtime_status": self._runtime_status,
            "last_success_at_epoch": self._last_success_at,
            "last_failure_at_epoch": self._last_failure_at,
            "last_error": self._last_error,
        }


__all__ = ["ScannerService"]
