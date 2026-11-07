"""Resolve only Kite credentials from process settings or a Render secret file."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values

FIELDS = ("KITE_API_KEY", "KITE_API_SECRET", "KITE_ACCESS_TOKEN")
MAX_SECRET_FILE_BYTES = 65_536


@dataclass(frozen=True)
class KiteEnvironment:
    # Credentials must never appear in diagnostic repr/log output.
    values: dict[str, str] = field(repr=False)
    source: str = "not_configured"
    secret_file_present: bool = False
    error_code: str | None = None


def resolve_kite_environment(
    environ: Mapping[str, str] | None = None,
) -> KiteEnvironment:
    env = os.environ if environ is None else environ
    values = {name: str(env.get(name) or "").strip() for name in FIELDS}
    path_value = str(env.get("TRENDFORGE_KITE_ENV_PATH") or "").strip()
    if not path_value and str(env.get("RENDER") or "").strip().lower() == "true":
        path_value = "/etc/secrets/kite.env"
    present = False
    error = None
    file_values: dict[str, str] = {}
    if path_value:
        try:
            path = Path(path_value).expanduser()
            present = path.is_file()
            if present and not all(values.values()):
                with path.open("rb") as stream:
                    raw = stream.read(MAX_SECRET_FILE_BYTES + 1)
                if len(raw) > MAX_SECRET_FILE_BYTES:
                    raise ValueError("Oversized credential file")
                parsed = dotenv_values(
                    stream=StringIO(raw.decode("utf-8-sig")), interpolate=False
                )
                file_values = {
                    name: str(parsed.get(name) or "").strip() for name in FIELDS
                }
        except (OSError, ValueError, UnicodeError):
            error = "credential_file_unreadable"

    used_file = False
    # Never silently build an API-key/token pair from different credential sets.
    key, token = values["KITE_API_KEY"], values["KITE_ACCESS_TOKEN"]
    file_key, file_token = (
        file_values.get("KITE_API_KEY", ""),
        file_values.get("KITE_ACCESS_TOKEN", ""),
    )
    if not key and not token and file_key and file_token:
        values["KITE_API_KEY"], values["KITE_ACCESS_TOKEN"] = file_key, file_token
        used_file = True
    elif key and not token and file_key == key and file_token:
        values["KITE_ACCESS_TOKEN"] = file_token
        used_file = True
    elif token and not key and file_token == token and file_key:
        values["KITE_API_KEY"] = file_key
        used_file = True
    elif bool(key) != bool(token) and file_key and file_token:
        error = "credential_sources_conflict"

    if (
        not values["KITE_API_SECRET"]
        and file_values.get("KITE_API_SECRET")
        and file_key == values["KITE_API_KEY"]
    ):
        values["KITE_API_SECRET"] = file_values["KITE_API_SECRET"]
        used_file = True
    source = (
        "secret_file"
        if used_file and not (key or token)
        else (
            "environment_with_file_fallback"
            if used_file
            else ("environment" if any(values.values()) else "not_configured")
        )
    )
    return KiteEnvironment(values, source, present, error)


def apply_kite_environment() -> KiteEnvironment:
    """Normalize/fill credential fields only; never read trading flags from file."""
    resolved = resolve_kite_environment()
    for name, value in resolved.values.items():
        if value:
            os.environ[name] = value
    return resolved
