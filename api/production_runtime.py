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
from api.scheduler_auth import scheduler_security_health
from core.database import database_health
from core.paper_storage_policy import paper_entry_storage_policy
from core.storage_config import production_runtime_enabled, storage_health
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

        match = re.fullmatch(r"([^=<>!~\s]+)==([^\s]+)", line)
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

        # uvloop is Linux/macOS-only; Windows uses Uvicorn's asyncio loop.
        if match.group(1).lower() == "uvloop" and platform.system() == "Windows":
            continue
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


def _protected_admin_request(method: str, path: str) -> bool:
    method = method.upper()
    if path == "/paper" or path.startswith("/paper/"):
        return True
    if method == "GET" and path in {
        "/portfolio", "/pnl", "/performance", "/workspace/paper-portfolio",
    }:
        return True
    if (
        method == "POST"
        and path == "/scan/universe/nifty500"
    ):
        return True
    if method == "POST" and path in {
        "/scan",
        "/technical/scan",
        "/technical/backtest",
        "/technical/portfolio-backtest",
    }:
        return True
    if method == "GET" and path.startswith("/scan/"):
        return True
    if method == "POST" and path == "/portfolio/sync":
        return True
    if method == "POST" and path == "/backtests":
        return True
    if method == "POST" and path == "/technical/validation/run":
        return True
    if method == "POST" and path == "/intelligence/refresh":
        return True
    if method == "POST" and path == "/institutional/refresh":
        return True
    if method == "POST" and path == "/sector-strength/refresh":
        return True
    if method == "POST" and path in {
        "/notifications/events",
        "/notifications/test",
        "/notifications/daily-summary/send",
    }:
        return True
    if (
        method in {"PUT", "DELETE"}
        and path == "/notifications/policy"
    ):
        return True
    if (
        method in {"PUT", "DELETE"}
        and path == "/operations/policy"
    ):
        return True
    if (
        method == "POST"
        and (
            path == "/operations/tick"
            or path == "/operations/audit/run"
            or path.startswith("/operations/run/")
        )
    ):
        return True
    if (
        method in {"POST", "PUT", "DELETE"}
        and path.startswith("/watchlists/")
    ):
        return True
    if (
        method == "POST"
        and path == "/market/context/refresh"
    ):
        return True
    if method == "PUT" and path.startswith("/fundamentals/"):
        return True
    return method == "POST" and path in {
        "/fundamentals/upload",
        "/fundamentals/completion/upload",
        "/fundamentals/bulk/upload",
    }


def _requires_persistent_storage(method: str, path: str) -> bool:
    method = method.upper()
    if method == "PUT" and path.startswith("/fundamentals/"):
        return True
    return method == "POST" and path in {
        "/fundamentals/upload",
        "/fundamentals/completion/upload",
        "/fundamentals/bulk/upload",
    }


def _protected_admin_query(request: Request) -> bool:
    """Refresh reads and detailed diagnostics carry administrative privileges.

    Match all boolean spellings accepted by FastAPI, and examine repeated query
    parameters so an intermediary choosing a different value cannot bypass auth.
    Ordinary cached reads remain public.
    """
    if request.method.upper() not in {"GET", "HEAD"}:
        return False
    flag = {
        "/universe/nifty500": "refresh",
        "/fundamentals/readiness": "refresh_universe",
        "/production/health": "details",
        "/health": "details",
    }.get(request.url.path)
    return bool(flag) and any(
        value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
        for value in request.query_params.getlist(flag)
    )


def _public_production_health(report: dict[str, object]) -> dict[str, object]:
    """Expose readiness without filesystem locations or exception messages."""
    allowed = {
        "database": {"status", "exists", "reason"},
        "storage": {
            "status", "database_path_configured", "verified_persistent",
            "persistent_mount_is_mountpoint", "database_within_persistent_mount",
            "restart_recovery_confirmed",
        },
        "security": {
            "status", "admin_api_key_configured", "minimum_key_length",
            "protected_header",
        },
        "scheduler_security": {
            "status", "scheduler_api_key_configured", "distinct_from_admin_api_key",
            "minimum_key_length", "protected_header", "scope",
        },
        "bootstrap": {"status"},
        "dependencies": {"status", "file_sha256", "locked_packages"},
        "deployment": {"render_git_commit", "python_version"},
    }
    public: dict[str, object] = {}
    for section, fields in allowed.items():
        values = report.get(section)
        public[section] = {
            name: value for name, value in values.items() if name in fields
        } if isinstance(values, dict) else {}
    dependencies = report.get("dependencies")
    if isinstance(dependencies, dict):
        public_dependencies = public["dependencies"]
        if isinstance(public_dependencies, dict):
            for field in ("missing", "mismatched"):
                values = dependencies.get(field)
                public_dependencies[field + "_count"] = (
                    len(values) if isinstance(values, list) else 0
                )
    return public


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
        if _protected_admin_request(
            request.method,
            request.url.path,
        ) or _protected_admin_query(request):
            try:
                validate_admin_api_key(
                    request.headers.get(ADMIN_API_KEY_HEADER)
                )
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers=exc.headers,
                )

        if request.method == "POST" and request.url.path == "/paper/open":
            policy = paper_entry_storage_policy(production=True)
            if not policy["entry_allowed"]:
                return JSONResponse(
                    status_code=423,
                    content={
                        "detail": policy["message"],
                        "error_code": "PAPER_STORAGE_REQUIRED",
                        "entry_storage_policy": policy,
                    },
                )

        if _requires_persistent_storage(
            request.method,
            request.url.path,
        ):
            storage = storage_health()
            allow_ephemeral = _enabled(
                "TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES",
                False,
            )
            if (
                not storage["verified_persistent"]
                and not allow_ephemeral
            ):
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
    def production_health(details: bool = False):
        report = {
            "database": database_health(),
            "storage": storage_health(),
            "security": admin_security_health(),
            "scheduler_security": scheduler_security_health(),
            "bootstrap": app.state.fundamentals_bootstrap,
            "dependencies": dependency_lock_health(),
            "deployment": {
                "render_git_commit": os.getenv("RENDER_GIT_COMMIT"),
                "render_service_id": os.getenv("RENDER_SERVICE_ID"),
                "python_version": platform.python_version(),
            },
        }
        return report if details else _public_production_health(report)

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
