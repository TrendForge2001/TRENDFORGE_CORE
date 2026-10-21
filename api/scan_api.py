"""
scan_api.py — deprecated stub.

All routes previously defined here (health, scan, portfolio, paper/open,
paper/monitor, paper) are fully implemented in api/app.py and served from
the production FastAPI application mounted in start.py.

This file is kept as a stub to avoid ImportError in any legacy import sites.
Nothing from this module is mounted or executed in production.
"""
from __future__ import annotations

from services.paper_trading_runtime import PaperTradingRuntime  # noqa: F401 – re-exported for any legacy import

__all__: list[str] = ["PaperTradingRuntime"]
