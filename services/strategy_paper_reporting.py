"""Complete period-filtered paper statements, including zero-trade strategies."""

from __future__ import annotations

from datetime import datetime
from math import fsum, isfinite
from typing import Any

from scanner.strategy_registry import list_strategies
from services.portfolio_performance_service import PortfolioPerformanceService


class StrategyPaperReporting:
    def __init__(self, paper_service: Any):
        self.paper = paper_service

    @staticmethod
    def _number(value: Any) -> float:
        if isinstance(value, bool):
            raise ValueError("Invalid paper accounting value")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Invalid paper accounting value") from None
        if not isfinite(number):
            raise ValueError("Invalid paper accounting value")
        return number

    def statement(self, *, period: str = "daily", now: datetime | None = None) -> dict:
        helpers = PortfolioPerformanceService
        current = now or helpers._now()
        current = (
            current.replace(tzinfo=helpers.MARKET_TZ)
            if current.tzinfo is None
            else current.astimezone(helpers.MARKET_TZ)
        )
        start = helpers._period_start(period, current)
        # Match the same runtime admission lock to avoid crossing an open/close
        # between the current position book and the realized ledger read.
        with self.paper.runtime._state_lock:
            snapshot = self.paper.runtime.snapshot()
            closed_rows = list(self.paper.runtime.trades.closed_trades())
        catalog = {row["strategy_id"]: row for row in list_strategies()}
        buckets = {}

        def bucket(row):
            key = (
                str(row.get("strategy_id") or "unattributed").strip().lower()
                or "unattributed"
            )
            if key not in buckets:
                definition = catalog.get(key, {})
                buckets[key] = {
                    "strategy_id": key,
                    "strategy_name": definition.get("name")
                    or row.get("strategy_name")
                    or "Manual / unattributed",
                    "source": definition.get("source") or row.get("strategy_source"),
                    "registered": key in catalog,
                    "closed_trades": [],
                    "open_positions": [],
                }
            return buckets[key]

        for definition in catalog.values():
            bucket(definition)
        for raw in closed_rows:
            row = dict(raw)
            opened = helpers._parse_datetime(row.get("created_at"))
            exited = helpers._parse_datetime(row.get("closed_at"))
            realized_at = exited or opened
            if realized_at is None:
                raise ValueError("Paper ledger has an invalid realized date")
            if realized_at > current or (start is not None and realized_at < start):
                continue
            row["pnl"] = self._number(row.get("pnl"))
            row["realized_at"] = realized_at.isoformat()
            row["date_basis"] = "closed_at" if exited else "legacy_entry_fallback"
            bucket(row)["closed_trades"].append(row)
        for row in snapshot["positions"]:
            row = dict(row)
            row["pnl"] = self._number(row.get("pnl"))
            bucket(row)["open_positions"].append(row)
        rows = []
        for item in buckets.values():
            values = [row["pnl"] for row in item["closed_trades"]]
            try:
                realized = self._number(fsum(values))
                unrealized = self._number(
                    fsum(row["pnl"] for row in item["open_positions"])
                )
                total = self._number(fsum((realized, unrealized)))
            except OverflowError:
                raise ValueError("Paper statement totals are invalid") from None
            rows.append(
                {
                    **item,
                    "trade_count": len(values),
                    "open_count": len(item["open_positions"]),
                    "wins": sum(value > 0 for value in values),
                    "losses": sum(value < 0 for value in values),
                    "realized_pnl": round(realized, 2),
                    "unrealized_pnl": round(unrealized, 2),
                    "total_pnl": round(total, 2),
                }
            )
        return {
            "scope": "strategy_paper_trading",
            "period": period,
            "period_start": start.isoformat() if start else None,
            "period_end": current.isoformat(),
            "strategy_count": len(catalog),
            "rows": rows,
            "paper_only": True,
            "broker_orders_allowed": False,
            "accounting": (
                "Realized by exit date; open P&L uses last marks, "
                "not period movement. Fees/slippage excluded."
            ),
        }
