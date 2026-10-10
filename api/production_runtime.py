"""Production-only security, bootstrap and persistence diagnostics."""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
from importlib import metadata
import os
import platform
from pathlib import Path
import re
from typing import Mapping

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from api.admin_auth import (
    ADMIN_API_KEY_HEADER,
    admin_security_health,
    validate_admin_api_key,
)
from core.database import database_health, database_path
from services.fundamental_bootstrap_service import FundamentalBootstrapService

DEFAULT_BOOTSTRAP_PATH = "/etc/secrets/trendforge_fundamentals_bootstrap.json"

PRODUCTION_LOCK_PATH = (
    Path(__file__).resolve().parents[1] / "requirements-production.lock"
)


def dependency_lock_health(
    path: str | Path = PRODUCTION_LOCK_PATH,
) -> dict[str, object]:
    lock_path = Path(path)
    if not lock_path.is_file():
        return {
            "status": "missing",
            "file": str(lock_path),
            "locked_packages": 0,
            "missing": [],
            "mismatched": [],
        }

    raw_bytes = lock_path.read_bytes()
    expected: dict[str, str] = {}

    for raw in raw_bytes.decode("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        match = re.fullmatch(r"([^=<>!~\\s]+)==([^\\s]+)", line)
        if not match:
            return {
                "status": "invalid",
                "file": str(lock_path),
                "file_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "locked_packages": len(expected),
                "invalid_entry": line,
                "missing": [],
                "mismatched": [],
            }

        expected[match.group(1)] = match.group(2)

    missing: list[str] = []
    mismatched: list[dict[str, str]] = []

    for name, version in expected.items():
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue

        if installed != version:
            mismatched.append(
                {
                    "package": name,
                    "expected": version,
                    "installed": installed,
                }
            )

    status = (
        "runtime_verified"
        if expected and not missing and not mismatched
        else "degraded"
    )

    return {
        "status": status,
        "file": str(lock_path),
        "file_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "locked_packages": len(expected),
        "missing": missing,
        "mismatched": mismatched,
    }



def _enabled(name: str, default: bool = False, environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    value = source.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def production_runtime_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return _enabled(
        "TRENDFORGE_PRODUCTION_RUNTIME",
        _enabled("RENDER", False, source),
        source,
    )


def storage_health() -> dict[str, object]:
    configured = os.getenv("DATABASE_PATH")
    target = Path(database_path()).expanduser()
    parent = target.parent.resolve()
    mounted = os.path.ismount(str(parent))
    verified = bool(configured and target.is_absolute() and mounted)
    return {
        "status": "persistent" if verified else "ephemeral_or_unverified",
        "database_path": str(target),
        "database_path_configured": bool(configured),
        "parent": str(parent),
        "parent_is_mountpoint": mounted,
        "verified_persistent": verified,
    }


def run_configured_bootstrap() -> dict[str, object]:
    configured = os.getenv("FUNDAMENTALS_BOOTSTRAP_PATH")
    default = Path(DEFAULT_BOOTSTRAP_PATH)
    path = configured or (str(default) if default.is_file() else None)
    if not path:
        return {"status": "not_configured"}
    expected = os.getenv("FUNDAMENTALS_BOOTSTRAP_SHA256")
    require_pinned = _enabled(
        "FUNDAMENTALS_BOOTSTRAP_REQUIRE_PINNED_SHA256",
        True,
    )
    service = FundamentalBootstrapService()
    try:
        return service.apply_bundle(
            path,
            expected_file_sha256=expected,
            require_pinned_sha256=require_pinned,
        )
    except Exception as exc:
        return {"status": "failed", "error": str(exc), "file": str(path)}
    finally:
        service.close()


def _protected_mutation(method: str, path: str) -> bool:
    method = method.upper()
    if method == "PUT" and path.startswith("/fundamentals/"):
        return True
    return method == "POST" and path in {
        "/fundamentals/upload",
        "/fundamentals/completion/upload",
    }


def secure_application(app):
    if getattr(app.state, "trendforge_production_runtime", False):
        return app
    app.state.trendforge_production_runtime = True
    app.state.fundamentals_bootstrap = {"status": "not_run"}

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def production_lifespan(application):
        async with original_lifespan(application) as state:
            application.state.fundamentals_bootstrap = run_configured_bootstrap()
            yield state

    app.router.lifespan_context = production_lifespan

    @app.middleware("http")
    async def protect_admin_mutations(request: Request, call_next):
        if _protected_mutation(request.method, request.url.path):
            try:
                validate_admin_api_key(request.headers.get(ADMIN_API_KEY_HEADER))
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers=exc.headers,
                )
            storage = storage_health()
            allow_ephemeral = _enabled(
                "TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES",
                False,
            )
            if not storage["verified_persistent"] and not allow_ephemeral:
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": (
                            "Administrative writes are disabled because "
                            "database storage is not verified persistent."
                        )
                    },
                )
        return await call_next(request)

    @app.get("/production/health")
    def production_health():
        return {
            "database": database_health(),
            "storage": storage_health(),
            "security": admin_security_health(),
            "bootstrap": app.state.fundamentals_bootstrap,
            "dependencies": dependency_lock_health(),
            "deployment": {
                "render_git_commit": os.getenv("RENDER_GIT_COMMIT"),
                "render_service_id": os.getenv("RENDER_SERVICE_ID"),
                "python_version": platform.python_version(),
            },
        }

    return app


__all__ = [
    "DEFAULT_BOOTSTRAP_PATH",
    "PRODUCTION_LOCK_PATH",
    "dependency_lock_health",
    "production_runtime_enabled",
    "run_configured_bootstrap",
    "secure_application",
    "storage_health",
]
