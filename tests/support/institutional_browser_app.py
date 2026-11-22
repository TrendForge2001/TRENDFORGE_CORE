"""Synthetic owner-only portfolio server; no broker or investor feed is used."""

import os
from types import SimpleNamespace

from fastapi import FastAPI

from api.big_shark_router import big_shark_router
from core.database import initialize_database
from core.unified_render import build_unified_app
from tests.support.public_feed_fixtures import SyntheticDaily, SyntheticPublic

initialize_database(os.environ["DATABASE_PATH"])
core = FastAPI()


core.include_router(
    big_shark_router(
        lambda: SimpleNamespace(market_data=SyntheticDaily()),
        public_provider_getter=SyntheticPublic,
    )
)
app = build_unified_app(core)
