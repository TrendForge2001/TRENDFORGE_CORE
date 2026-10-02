"""Validated runtime configuration for TrendForge Core.

The module reads environment variables without performing network or broker
initialization.  Validation is explicit so deployment checks can distinguish
optional configuration from credentials required for a specific operation.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeConfig:
    kite_api_key: str | None = None
    kite_api_secret: str | None = None
    kite_access_token: str | None = None
    discord_webhook: str | None = None
    database_url: str | None = None

    @property
    def kite_configured(self) -> bool:
        return bool(self.kite_api_key and self.kite_api_secret)

    @property
    def kite_authenticated(self) -> bool:
        return bool(self.kite_configured and self.kite_access_token)

    def missing_kite_credentials(self) -> tuple[str, ...]:
        missing = []
        if not self.kite_api_key:
            missing.append("KITE_API_KEY")
        if not self.kite_api_secret:
            missing.append("KITE_API_SECRET")
        return tuple(missing)


def load_runtime_config(environ: dict[str, str] | None = None) -> RuntimeConfig:
    source = os.environ if environ is None else environ
    return RuntimeConfig(
        kite_api_key=source.get("KITE_API_KEY") or None,
        kite_api_secret=source.get("KITE_API_SECRET") or None,
        kite_access_token=source.get("KITE_ACCESS_TOKEN") or None,
        discord_webhook=source.get("DISCORD_WEBHOOK") or None,
        database_url=source.get("DATABASE_URL") or None,
    )


def validate_runtime_config(
    config: RuntimeConfig | None = None,
    *,
    require_kite: bool = False,
) -> tuple[str, ...]:
    """Return configuration errors without raising during import/startup."""
    current = config or load_runtime_config()
    errors: list[str] = []

    if require_kite:
        missing = current.missing_kite_credentials()
        if missing:
            errors.append("Missing required Kite configuration: " + ", ".join(missing))

    if current.kite_access_token and not current.kite_configured:
        errors.append(
            "KITE_ACCESS_TOKEN is set but KITE_API_KEY and KITE_API_SECRET are incomplete"
        )

    return tuple(errors)


__all__ = ["RuntimeConfig", "load_runtime_config", "validate_runtime_config"]
