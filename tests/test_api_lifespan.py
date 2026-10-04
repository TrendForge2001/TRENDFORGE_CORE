from __future__ import annotations

import asyncio

from api.app import create_app
from core.application_factory import ApplicationFactory
from core.database import database_health


class FakeProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        raise RuntimeError("not used")


async def _run_lifespan(app):
    async with app.router.lifespan_context(app):
        return app.state.database


def test_api_lifespan_initializes_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "trendforge.db"))
    app = create_app(
        application_factory=ApplicationFactory(
            kite=FakeProvider(), yahoo=FakeProvider()
        )
    )

    database_state = asyncio.run(_run_lifespan(app))

    assert database_state["status"] == "initialized"
    assert database_health()["status"] == "ready"
