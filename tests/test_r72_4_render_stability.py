from __future__ import annotations

import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from core.unified_render import build_unified_app
from services.technical_auto_scanner import TechnicalAutoScanner


def test_swing_scheduler_does_not_backfill_after_morning_window(monkeypatch):
    monkeypatch.delenv("TRENDFORGE_TECHNICAL_SWING_GRACE_MINUTES", raising=False)
    runner = TechnicalAutoScanner(technical_service=object())
    tz = ZoneInfo("Asia/Kolkata")

    assert runner._swing_slot(datetime(2026, 10, 21, 9, 24, tzinfo=tz)) is None
    assert runner._swing_slot(datetime(2026, 10, 21, 9, 25, tzinfo=tz)) == (
        "swing:2026-10-21"
    )
    assert runner._swing_slot(datetime(2026, 10, 21, 9, 44, tzinfo=tz)) == (
        "swing:2026-10-21"
    )
    assert runner._swing_slot(datetime(2026, 10, 21, 9, 46, tzinfo=tz)) is None
    assert runner._swing_slot(datetime(2026, 10, 21, 20, 0, tzinfo=tz)) is None


def test_unified_render_health_is_constant_time_liveness():
    core = FastAPI()

    @core.get("/health")
    def diagnostic_health():
        return {"status": "diagnostic"}

    app = build_unified_app(core)
    health_route = next(
        route for route in app.routes
        if getattr(route, "path", None) == "/health"
    )
    response = asyncio.run(health_route.endpoint(None))
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload == {
        "service": "TrendForge Core",
        "status": "ok",
        "liveness": "pass",
        "unified_ui": True,
    }
