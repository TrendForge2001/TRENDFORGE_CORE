"""Runtime configuration validation for TrendForge."""
from __future__ import annotations

from typing import Any

from config import settings


def _configured(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def runtime_health() -> dict[str, Any]:
    """Report runtime readiness without exposing credentials."""
    checks = {
        "kite_api_key": _configured(getattr(settings, "KITE_API_KEY", None)),
        "kite_api_secret": _configured(getattr(settings, "KITE_API_SECRET", None)),
        "kite_access_token": _configured(getattr(settings, "KITE_ACCESS_TOKEN", None)),
        "discord_webhook": _configured(getattr(settings, "DISCORD_WEBHOOK", None)),
        "database_url": _configured(getattr(settings, "DATABASE_URL", None)),
    }
    required = ("kite_api_key", "kite_api_secret", "database_url")
    missing_required = [name for name in required if not checks[name]]
    return {
        "status": "healthy" if not missing_required else "degraded",
        "checks": checks,
        "missing_required": missing_required,
        "broker_ready": all(checks[name] for name in ("kite_api_key", "kite_api_secret", "kite_access_token")),
    }


__all__ = ["runtime_health"]
