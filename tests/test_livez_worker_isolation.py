"""Render liveness must work even when synchronous API workers are occupied."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import anyio
import httpx
import pytest

from api.app import create_app


def _unified(core, monkeypatch):
    pytest.importorskip("streamlit")
    from core import unified_render

    class StreamlitStub:
        def __init__(self, script):
            assert Path(script).is_absolute()
            assert Path(script).is_file()

        def lifespan(self):
            @asynccontextmanager
            async def lifespan(app):
                yield
            return lifespan

        async def __call__(self, scope, receive, send):
            raise AssertionError("Liveness entered Streamlit")

    # Streamlit owns a process singleton; routing tests must not construct it.
    # The actual lifecycle is verified separately by a subprocess cold boot.
    monkeypatch.setattr(unified_render, "StreamlitApp", StreamlitStub)
    return unified_render.build_unified_app(core)


@pytest.mark.parametrize("unified", [False, True])
def test_livez_does_not_wait_for_sync_worker_capacity(unified, monkeypatch):
    app = create_app(SimpleNamespace())
    if unified:
        app = _unified(app, monkeypatch)

    async def scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        borrower = object()
        limiter.total_tokens = 1
        await limiter.acquire_on_behalf_of(borrower)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                with anyio.fail_after(1):
                    response = await client.get("/livez")
                    head = await client.head("/livez")
                assert response.status_code == 200
                assert response.json()["status"] == "ok"
                assert head.status_code == 200
                assert not head.content
        finally:
            limiter.release_on_behalf_of(borrower)
            limiter.total_tokens = previous

    asyncio.run(scenario())


def test_unified_livez_bypasses_core_middleware(monkeypatch):
    from fastapi import FastAPI

    core = FastAPI()

    @core.middleware("http")
    async def blocked_core(request, call_next):
        raise AssertionError("Liveness entered core middleware")

    app = _unified(core, monkeypatch)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/livez")
        assert response.status_code == 200
        assert response.json()["unified_ui"] is True

    asyncio.run(scenario())
