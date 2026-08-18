"""Health reporting for TrendForge reconstruction components."""

from __future__ import annotations

from typing import Any


class ReconstructionHealth:
    """Aggregate health from independently replaceable components."""

    def __init__(self, components: dict[str, Any] | None = None):
        self.components = components or {}

    def report(self) -> dict[str, Any]:
        details: dict[str, Any] = {}
        degraded = False
        for name, component in self.components.items():
            try:
                status = component.health() if hasattr(component, "health") else {"status": "configured"}
            except Exception as exc:
                status = {"status": "error", "error": str(exc)}
            details[name] = status
            if status.get("status") not in {"healthy", "configured"}:
                degraded = True
        return {
            "status": "degraded" if degraded else "healthy",
            "components": details,
        }


__all__ = ["ReconstructionHealth"]
