"""Synthetic owner-only portfolio server; no broker or investor feed is used."""

import os
from types import SimpleNamespace

import numpy as np
import pandas as pd
from fastapi import FastAPI

from api.big_shark_router import big_shark_router
from core.database import initialize_database
from core.unified_render import build_unified_app

initialize_database(os.environ["DATABASE_PATH"])
core = FastAPI()


class SyntheticDaily:
    def candles(self, symbol, **kwargs):
        dates = pd.bdate_range(
            "2022-01-03",
            pd.Timestamp.now("Asia/Kolkata").date(),
            tz="Asia/Kolkata",
        )
        close = 100 + np.arange(len(dates)) * 0.02 + np.sin(np.arange(len(dates)))
        return pd.DataFrame(
            {
                "open": close - 0.1,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1000.0,
            },
            index=dates,
        )


core.include_router(
    big_shark_router(lambda: SimpleNamespace(market_data=SyntheticDaily()))
)
app = build_unified_app(core)
