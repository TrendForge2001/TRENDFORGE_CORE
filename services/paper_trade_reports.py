"""Read-only paper ledger reports, including partial and historical exit fills."""

from datetime import datetime
from math import fsum, isfinite

from services.portfolio_performance_service import PortfolioPerformanceService as Dates


def number(value):
    if isinstance(value, bool):
        raise ValueError("Invalid paper accounting value")
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Invalid paper accounting value") from None
    if not isfinite(value):
        raise ValueError("Invalid paper accounting value")
    return value


def cashflows(row, *, closed):
    qty = number(row["quantity"])
    entry = number(row.get("entry_price", row.get("average_price")))
    if qty <= 0 or int(qty) != qty or entry <= 0:
        raise ValueError("Invalid paper fill")
    exit_value = number(number(row["exit_price"]) * qty) if closed else 0.0
    if closed and exit_value <= 0:
        raise ValueError("Invalid paper exit fill")
    entry_value = number(entry * qty)
    side = str(row.get("side", "")).upper()
    if side not in {"BUY", "LONG", "SHORT", "SELL"}:
        raise ValueError("Paper fill direction is invalid")
    short = side in {"SHORT", "SELL"}
    return (exit_value, entry_value) if short else (entry_value, exit_value)


class PaperTradeReports:
    def __init__(self, paper):
        self.paper = paper

    def statement(self, *, period="all", now=None):
        runtime = self.paper.runtime
        with runtime._state_lock:
            snapshot = runtime.snapshot()
            closed = [dict(row) for row in runtime.trades.closed_trades()]
            ids = dict(runtime._trade_ids)
            # Stamp after the atomic read so an exit completed while waiting
            # for this lock is included in the same report's closed ledger.
            current = now or datetime.now(Dates.MARKET_TZ)
        current = (
            current.replace(tzinfo=Dates.MARKET_TZ)
            if current.tzinfo is None
            else current.astimezone(Dates.MARKET_TZ)
        )
        start = Dates._period_start(period, current)
        all_closed, selected = [], []
        for row in closed:
            stamp = Dates._parse_datetime(row.get("closed_at"))
            fallback = stamp is None
            stamp = stamp or Dates._parse_datetime(row.get("created_at"))
            if stamp is None:
                raise ValueError("Paper exit date is unavailable")
            if stamp > current:
                continue
            buy, sell = cashflows(row, closed=True)
            item = {
                **row,
                "realized_at": stamp.isoformat(),
                "date_basis": "legacy_entry_fallback" if fallback else "closed_at",
                "realized_pnl": number(row["pnl"]),
                "unrealized_pnl": 0.0,
                "buy_value": buy,
                "sell_value": sell,
                # A historical exit is never presented as a current quote.
                "ltp": None,
            }
            all_closed.append(item)
            if start is None or stamp >= start:
                selected.append(item)
        selected.sort(
            key=lambda row: (row["realized_at"], str(row.get("id"))), reverse=True
        )
        positions = []
        for raw in snapshot["positions"]:
            row = dict(raw)
            trade_id = ids.get(row["symbol"])
            legs = [
                leg
                for leg in all_closed
                if trade_id is not None and leg.get("parent_trade_id") == trade_id
            ]
            buy, sell = cashflows(row, closed=False)
            positions.append(
                {
                    **row,
                    "trade_id": trade_id,
                    "realized_pnl": fsum(leg["realized_pnl"] for leg in legs)
                    if trade_id is not None
                    else None,
                    "unrealized_pnl": number(row["pnl"]),
                    "buy_value": buy + fsum(leg["buy_value"] for leg in legs),
                    "sell_value": sell + fsum(leg["sell_value"] for leg in legs),
                }
            )
        return {
            "scope": "paper_trade_reports",
            "period": period,
            "period_start": start.isoformat() if start else None,
            "period_end": current.isoformat(),
            "portfolio": {**snapshot, "positions": positions},
            "closed_trades": selected,
            "summary": {
                "closed_fills": len(selected),
                "realized_pnl": round(fsum(row["realized_pnl"] for row in selected), 2),
                "buy_value": round(fsum(row["buy_value"] for row in selected), 2),
                "sell_value": round(fsum(row["sell_value"] for row in selected), 2),
            },
            "accounting": (
                "Closed fills are filtered by exit date in IST, "
                "including partial exits. "
                "All time includes every saved fill; scanner report retention does not "
                "delete paper trades. Buy/sell values are actual simulated fill values "
                "before fees; realised P&L retains the ledger's recorded cost basis. "
                "Open marks are saved marks, not evidence of a fresh quote. "
                "Open-position cashflows include partial exit legs; "
                "do not add them again to the closed-fill totals."
            ),
            "paper_only": True,
            "broker_orders_allowed": False,
        }
