"""Bounded visibility into production ASGI imports, without provider probes."""
from __future__ import annotations

from contextlib import contextmanager
import faulthandler
import os
import sys
import time


@contextmanager
def startup_import(*, stall_seconds: float = 60):
    enabled = str(
        os.getenv("TRENDFORGE_PRODUCTION_RUNTIME", os.getenv("RENDER", "false"))
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        yield
        return

    started = time.monotonic()
    print("TRENDFORGE_BOOT phase=asgi_import status=starting", file=sys.stderr, flush=True)
    # Stack traces contain code locations, not credential values or locals.
    # If an import stalls before Uvicorn logs its startup, Render now has evidence.
    faulthandler.dump_traceback_later(stall_seconds, repeat=True, file=sys.stderr)
    succeeded = False
    try:
        yield
        succeeded = True
    finally:
        faulthandler.cancel_dump_traceback_later()
        status = "complete" if succeeded else "failed"
        print(
            f"TRENDFORGE_BOOT phase=asgi_import status={status} "
            f"elapsed_seconds={time.monotonic() - started:.3f}",
            file=sys.stderr,
            flush=True,
        )
