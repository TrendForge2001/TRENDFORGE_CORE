"""Serve the compiled workbench and its owner-only Core routes in the unified app."""

from __future__ import annotations

import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from api.admin_auth import (
    ADMIN_API_KEY_ENV,
    ADMIN_API_KEY_HEADER,
    MIN_ADMIN_API_KEY_LENGTH,
)
from config.stock_lists import EQUITY_STOCK_LISTS
from core.workbench_assets import WORKBENCH_BUNDLE_PATH, workbench_entries

ROOT = "/app/workbench"
API_ROOT = ROOT + "/api/core"
BUNDLE = Path(__file__).resolve().parents[1] / WORKBENCH_BUNDLE_PATH
READ = re.compile(
    r"/(?:reports/batches(?:/[\w.:-]+/(?:workbench|consolidated\.xlsx|report\.(?:csv|xlsx)))?"
    r"|reports/stocks/[A-Z0-9][A-Z0-9._&-]{0,29}(?:/report\.html)?"
    r"|reports/backtest-queue(?:/queued-stocks\.xlsx|/[\w.:-]+/trades\.xlsx)?"
    r"|workbench/(?:catalog|benchmark|candles/[A-Z0-9._&-]+)"
    r"|institutional/big-shark/selector"
    r"|(?:production/)?health)"
)
WATCHLIST_READS = frozenset(
    f"/workspace/watchlist/{name}/constituents" for name in EQUITY_STOCK_LISTS
)
WRITE = frozenset(
    {"/reports/scan", "/reports/backtest", "/reports/backtest-queue/start"}
)
SCAN_RECHECK = re.compile(r"/reports/batches/[\w.:-]+/retry-errors")
ADMIN_HEADER = ADMIN_API_KEY_HEADER.lower().encode("ascii")


class OwnerWorkbenchAPI:
    """Dispatch the research allowlist inside Core using its server credential.

    The unified application's owner middleware authenticates this entire mount.
    The browser never receives an administrative credential.
    """

    def __init__(self, core_app):
        self.core_app = core_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        path = scope["path"].removeprefix(scope["root_path"])
        method = scope["method"]
        if ".." in path or not (
            (method == "GET" and (path in WATCHLIST_READS or READ.fullmatch(path)))
            or (method == "POST" and (path in WRITE or SCAN_RECHECK.fullmatch(path)))
        ):
            response = JSONResponse({"detail": "Route unavailable"}, status_code=404)
        elif method == "POST" and (
            (b"x-trendforge-workbench", b"1") not in scope["headers"]
            or (b"content-type", b"application/json") not in scope["headers"]
        ):
            response = JSONResponse(
                {"detail": "Invalid workbench request"}, status_code=403
            )
        else:
            key = os.getenv(ADMIN_API_KEY_ENV, "").strip()
            if len(key) >= MIN_ADMIN_API_KEY_LENGTH:
                headers = [
                    (name, value)
                    for name, value in scope["headers"]
                    if name != ADMIN_HEADER
                ]
                headers.append((ADMIN_HEADER, key.encode("utf-8")))
                upstream = {
                    **scope,
                    "path": path,
                    "raw_path": path.encode("utf-8"),
                    "root_path": "",
                    "app_root_path": "",
                    "headers": headers,
                }
                if path in {"/production/health", "/health"} and not scope.get("query_string"):
                    upstream["query_string"] = b"details=true"
                await self.core_app(upstream, receive, send)
                return
            response = JSONResponse(
                {"detail": "The Core admin key is unavailable on the server"},
                status_code=503,
            )
        await response(scope, receive, send)


def workbench_routes(core_app, streamlit_app, bundle=None):
    """Return private routes and their static bundle lifetime when installed."""
    archive = BUNDLE if bundle is None else bundle
    if not archive.is_file():
        return [], None
    extracted = TemporaryDirectory(prefix="trendforge-workbench-")
    try:
        with ZipFile(archive) as contents:
            entries = workbench_entries(contents, archive.stat().st_size)
            contents.extractall(extracted.name, members=entries)
        directory = Path(extracted.name)
        for view in ("scanner", "stocks", "backtests", "strategies", "runs", "health"):
            if not (directory / view / "index.html").is_file():
                raise RuntimeError(f"Incomplete TrendForge workbench bundle: {view}")
        static = StaticFiles(directory=directory, html=True)
    except Exception:
        extracted.cleanup()
        raise

    async def scanner(_request):
        return RedirectResponse(ROOT + "/scanner/", status_code=307)

    return [
        Route("/app/", scanner, methods=["GET", "HEAD"]),
        Route(ROOT + "/", scanner, methods=["GET", "HEAD"]),
        Mount(API_ROOT, app=OwnerWorkbenchAPI(core_app), name="workbench-api"),
        Mount(ROOT, app=static, name="workbench-ui"),
        Mount("/app/classic", app=streamlit_app, name="trendforge-classic"),
    ], extracted
