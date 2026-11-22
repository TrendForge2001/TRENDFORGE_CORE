"""Synthetic visual-report server. No broker, owner workbook or public feed."""

import math
from datetime import UTC, datetime, timedelta

import pandas as pd

from api.stock_report_router import stock_report_router
from services.trading_calendar import latest_completed_session
from tests.support.design_browser_app import app as app
from tests.support.design_browser_app import core


class ReportMarket:
    def candles(self, *args, **kwargs):
        dates = pd.bdate_range(
            end=latest_completed_session(datetime.now(UTC)),
            periods=252,
            tz="Asia/Kolkata",
        )
        values = [387 + 45 * (1 - i / 251) + 8 * math.sin(i / 7) for i in range(252)]
        shift = values[-1] - 387
        values = [value - shift for value in values]
        return pd.DataFrame(
            {
                "open": [v - 1 for v in values],
                "high": [v + 3 for v in values],
                "low": [v - 3 for v in values],
                "close": values,
                "volume": [200000 + (i % 9) * 10000 for i in range(252)],
            },
            index=dates,
        )


class ReportTechnical:
    market_data = ReportMarket()

    def scan(self, **kwargs):
        assert kwargs["execute_paper"] is False
        long = kwargs["horizon"] == "long_term"
        return {
            "results": [
                {
                    "symbol": kwargs["symbols"][0],
                    "signal": "BUY",
                    "data_status": "READY",
                    "entry": 387,
                    "stoploss": 363.8,
                    "indicators": {
                        "EMA_20": 385,
                        "EMA_50": 375,
                        "EMA_100": 365,
                        "EMA_200": 350,
                        "RSI_WILDER_14": 58.2,
                        "volume": 250000,
                        "VOL_SMA_20": 200000,
                        "FIB_YEAR_S1": 363.8,
                        "FIB_YEAR_R1": 410.2,
                    },
                    "entry_plan": {
                        "entry": 387,
                        "stoploss": 363.8,
                        "partial_target": 410.2 if long else None,
                        "second_target": 430 if long else None,
                        "target2": 450 if long else None,
                        "stop_is_resting_order": False,
                        "entry_order_type": "NEXT_CANDLE_OPEN",
                    },
                    "institutional_rating": {
                        "rating": "BUY",
                        "score": 78.5,
                        "activity_signal": "BUY",
                        "data_coverage": "SYNTHETIC_TEST_FIXTURE",
                        "reason": (
                            "Synthetic disclosed buying and technical evidence align."
                        ),
                        "disclosure_time": None,
                    },
                }
            ]
        }


class ReportCompany:
    def get(self, *args, **kwargs):
        return {
            "status": "available",
            "company_name": "Example Telecom Ltd · synthetic preview",
            "source": "Synthetic example",
            "source_url": "https://example.com/company",
            "fetched_at": datetime.now(UTC).isoformat(),
            "facts_as_of": None,
            "reporting_basis": "Consolidated",
            "metrics": {
                "pe": 14.36,
                "dividend_yield_pct": 3.6,
                "market_cap_cr": 102097,
            },
            "annual": [
                {
                    "period": f"Mar {year}",
                    "period_end": f"{year}-03-31",
                    "revenue_cr": revenue,
                    "net_profit_cr": profit,
                }
                for year, revenue, profit in [
                    (2022, 28175, 4100),
                    (2023, 28959, 4500),
                    (2024, 30090, 5100),
                    (2025, 30886, 5500),
                    (2026, 33311, 6100),
                ]
            ],
            "quarterly": [
                {
                    "period": period,
                    "period_end": end,
                    "revenue_cr": revenue,
                    "net_profit_cr": profit,
                }
                for period, end, revenue, profit in [
                    ("Dec 2025", "2025-12-31", 7900, 1300),
                    ("Mar 2026", "2026-03-31", 8100, 1500),
                    ("Jun 2026", "2026-06-30", 8400, 1600),
                    ("Sep 2026", "2026-09-30", 8900, -100),
                ]
            ],
            "shareholding": [
                {
                    "period": period,
                    "period_end": end,
                    "complete": True,
                    "total_percent": 100,
                    "categories": [
                        {"category": name, "percent": value}
                        for name, value in [
                            ("Promoters", 51.3),
                            ("FII", 21),
                            ("DII", 23.2),
                            ("Public", 4.5),
                        ]
                    ],
                }
                for period, end in [
                    ("Jun 2026", "2026-06-30"),
                    ("Sep 2026", "2026-09-30"),
                ]
            ],
        }


class ReportNews:
    def news(self, symbol):
        return [
            {
                "title": (
                    "Example Telecom publishes quarterly results · synthetic headline"
                ),
                "link": "https://example.com/results",
                "publisher": "Synthetic exchange bulletin",
                "published": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            }
        ]


core.include_router(
    stock_report_router(
        lambda: ReportTechnical(),
        company_provider=ReportCompany(),
        news_getter=lambda: ReportNews(),
        market_label="Synthetic candle fixture",
    )
)
