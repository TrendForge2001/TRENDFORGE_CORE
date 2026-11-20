"""Synthetic owner-only portfolio server; no broker or investor feed is used."""

import os
from datetime import timedelta
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


class SyntheticPublic:
    def holdings(self, *, now):
        return {
            "rows": [
                {
                    "stock_name": "Example",
                    "investor_name": "Fund A",
                    "reported_action": "BOUGHT",
                    "holding_percent": 5.0,
                    "reported_change": "New",
                    "holding_value_cr": 100.0,
                    "quantity_held": 9999999,
                    "reporting_period": None,
                    "source_url": "https://www.moneycontrol.com/india-investors-portfolio/top-stocks-bought-sold",
                    "disclosed_at": None,
                    "is_actual_trade": False,
                }
            ],
            "investors": [
                {
                    "category": "Individual",
                    "investor_name": "Fund A",
                    "url": "https://www.moneycontrol.com/india-investors-portfolio/fund-a",
                }
            ],
            "document_sha256": "a" * 64,
            "reporting_period": None,
            "period_status": "UNKNOWN",
            "source_url": "https://www.moneycontrol.com/india-investors-portfolio/top-stocks-bought-sold",
            "coverage": "VISIBLE_PUBLIC_ROWS_ONLY",
            "disclosure_time_basis": "UNKNOWN",
        }

    def trades(self, *, source, start, end, now):
        from services.big_shark_activity import normalise_records

        records = [
            {
                "trade_date": (now - timedelta(days=1)).date().isoformat(),
                "symbol": "EXAMPLE",
                "stock_name": "Example",
                "investor_name": "Fund A",
                "side": side,
                "quantity": quantity,
                "price": "10.0",
            }
            for side, quantity in (("BUY", 12), ("SELL", 30))
        ]
        return {
            "rows": normalise_records(records, now=now)[0],
            "source": source,
            "coverage": "DISCLOSED_ONLY",
            "document_sha256": "b" * 64,
            "source_url": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals",
        }


core.include_router(
    big_shark_router(
        lambda: SimpleNamespace(market_data=SyntheticDaily()),
        public_provider_getter=SyntheticPublic,
    )
)
app = build_unified_app(core)
