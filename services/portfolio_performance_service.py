"""Read-only portfolio, P&L and performance reporting contracts."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from database.repositories.live_portfolio_repository import (
    LivePortfolioRepository,
)
from database.repositories.trade_repository import TradeRepository
from services.live_portfolio_sync import LivePortfolioSyncService


class PortfolioPerformanceService:
    """Build reporting views from persisted portfolio and trade history."""

    MARKET_TZ = ZoneInfo("Asia/Kolkata")
    PERIODS = {"daily", "weekly", "monthly", "yearly", "all"}

    def __init__(
        self,
        *,
        portfolio_repository: LivePortfolioRepository | None = None,
        trade_repository: TradeRepository | None = None,
        broker: Any | None = None,
    ) -> None:
        self._owns_portfolio = portfolio_repository is None
        self._owns_trades = trade_repository is None
        self.portfolio_repository = (
            portfolio_repository or LivePortfolioRepository()
        )
        self.trade_repository = trade_repository or TradeRepository()
        self.broker = broker

    @classmethod
    def _now(cls) -> datetime:
        return datetime.now(cls.MARKET_TZ)

    @classmethod
    def _parse_datetime(
        cls,
        value: Any,
    ) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value).strip()
            if not text:
                return None
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=cls.MARKET_TZ)
        return parsed.astimezone(cls.MARKET_TZ)

    @classmethod
    def _period_start(
        cls,
        period: str,
        now: datetime,
    ) -> datetime | None:
        value = str(period or "all").strip().lower()
        if value not in cls.PERIODS:
            raise ValueError(
                "period must be daily, weekly, monthly, yearly or all"
            )
        current = now.astimezone(cls.MARKET_TZ)
        if value == "all":
            return None
        if value == "daily":
            return current.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        if value == "weekly":
            start = current - timedelta(days=current.weekday())
            return start.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        if value == "monthly":
            return current.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        return current.replace(
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    @staticmethod
    def _dict_rows(rows: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows or []:
            if isinstance(row, dict):
                result.append(dict(row))
                continue
            try:
                result.append(dict(row))
            except (TypeError, ValueError):
                continue
        return result

    @staticmethod
    def _round(value: Any) -> float:
        try:
            number = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return round(number, 2) if isfinite(number) else 0.0

    def portfolio(self) -> dict[str, Any]:
        rows = self._dict_rows(self.portfolio_repository.all())
        holdings = [
            row
            for row in rows
            if str(row.get("book") or "").upper() == "HOLDING"
        ]
        positions = [
            row
            for row in rows
            if str(row.get("book") or "").upper() == "POSITION"
        ]

        investment = self._round(
            self.portfolio_repository.investment()
        )
        current_value = self._round(
            self.portfolio_repository.portfolio_value()
        )
        pnl = self._round(
            self.portfolio_repository.total_pnl()
        )
        pnl_pct = (
            round(pnl * 100.0 / investment, 2)
            if investment
            else 0.0
        )

        by_book: list[dict[str, Any]] = []
        for label, group in (
            ("HOLDING", holdings),
            ("POSITION", positions),
        ):
            book_investment = sum(
                float(row.get("investment") or 0.0)
                for row in group
            )
            book_value = sum(
                float(row.get("current_value") or 0.0)
                for row in group
            )
            book_pnl = sum(
                float(row.get("pnl") or 0.0)
                for row in group
            )
            by_book.append(
                {
                    "book": label,
                    "count": len(group),
                    "investment": self._round(book_investment),
                    "current_value": self._round(book_value),
                    "pnl": self._round(book_pnl),
                    "pnl_pct": (
                        round(
                            book_pnl * 100.0 / book_investment,
                            2,
                        )
                        if book_investment
                        else 0.0
                    ),
                }
            )

        sectors: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {
                "count": 0,
                "investment": 0.0,
                "current_value": 0.0,
                "pnl": 0.0,
            }
        )
        for row in holdings:
            sector = str(
                row.get("sector") or "Unclassified"
            ).strip() or "Unclassified"
            bucket = sectors[sector]
            bucket["count"] = int(bucket["count"]) + 1
            bucket["investment"] = float(
                bucket["investment"]
            ) + float(row.get("investment") or 0.0)
            bucket["current_value"] = float(
                bucket["current_value"]
            ) + float(row.get("current_value") or 0.0)
            bucket["pnl"] = float(
                bucket["pnl"]
            ) + float(row.get("pnl") or 0.0)

        sector_summary = []
        for sector, values in sorted(
            sectors.items(),
            key=lambda item: float(
                item[1]["current_value"]
            ),
            reverse=True,
        ):
            sector_summary.append(
                {
                    "sector": sector,
                    "count": int(values["count"]),
                    "investment": self._round(
                        values["investment"]
                    ),
                    "current_value": self._round(
                        values["current_value"]
                    ),
                    "pnl": self._round(values["pnl"]),
                }
            )

        latest = max(
            (
                self._parse_datetime(row.get("updated_at"))
                for row in rows
            ),
            default=None,
            key=lambda value: (
                value is not None,
                value or datetime.min.replace(
                    tzinfo=self.MARKET_TZ
                ),
            ),
        )

        return {
            "status": "ready" if rows else "empty",
            "scope": "persisted_live_portfolio",
            "count": len(rows),
            "holding_count": len(holdings),
            "position_count": len(positions),
            "investment": investment,
            "portfolio_value": current_value,
            "total_pnl": pnl,
            "total_pnl_pct": pnl_pct,
            "latest_updated_at": (
                latest.isoformat()
                if latest is not None
                else None
            ),
            "holdings": holdings,
            "positions": positions,
            "book_summary": by_book,
            "sector_summary": sector_summary,
        }

    def sync_portfolio(self) -> dict[str, Any]:
        broker = self.broker
        if broker is None:
            raise RuntimeError(
                "Kite portfolio synchronization is not configured"
            )
        logged_in = getattr(broker, "is_logged_in", None)
        if callable(logged_in) and not logged_in():
            raise RuntimeError(
                "Kite broker session is not connected"
            )
        if not callable(getattr(broker, "holdings", None)):
            raise RuntimeError(
                "Configured broker does not expose holdings"
            )
        if not callable(getattr(broker, "positions", None)):
            raise RuntimeError(
                "Configured broker does not expose positions"
            )

        service = LivePortfolioSyncService(
            broker,
            repository=self.portfolio_repository,
        )
        result = service.sync()
        result["scope"] = "live_kite_portfolio"
        return result

    def _closed_trades(
        self,
        *,
        period: str = "all",
        now: datetime | None = None,
    ) -> tuple[
        list[dict[str, Any]],
        datetime | None,
        datetime,
    ]:
        current = (
            now.astimezone(self.MARKET_TZ)
            if now is not None and now.tzinfo is not None
            else (
                now.replace(tzinfo=self.MARKET_TZ)
                if now is not None
                else self._now()
            )
        )
        start = self._period_start(period, current)

        trades: list[dict[str, Any]] = []
        for row in self._dict_rows(
            self.trade_repository.closed_trades()
        ):
            closed_at = self._parse_datetime(
                row.get("closed_at")
            )
            opened_at = self._parse_datetime(
                row.get("created_at")
            )
            realized_at = closed_at or opened_at
            if realized_at is None:
                continue
            if start is not None and realized_at < start:
                continue
            if realized_at > current:
                continue

            trades.append(
                {
                    "id": row.get("id"),
                    "symbol": row.get("symbol"),
                    "side": row.get("side"),
                    "quantity": int(
                        row.get("quantity") or 0
                    ),
                    "entry_price": self._round(
                        row.get("entry_price")
                    ),
                    "exit_price": self._round(
                        row.get("exit_price")
                    ),
                    "pnl": self._round(row.get("pnl")),
                    "status": row.get("status"),
                    "opened_at": (
                        opened_at.isoformat()
                        if opened_at is not None
                        else None
                    ),
                    "closed_at": (
                        closed_at.isoformat()
                        if closed_at is not None
                        else None
                    ),
                    "realized_at": realized_at.isoformat(),
                    "date_basis": (
                        "closed_at"
                        if closed_at is not None
                        else "legacy_entry_fallback"
                    ),
                    "entry_value": self._round(
                        abs(
                            int(row.get("quantity") or 0)
                            * float(
                                row.get("entry_price") or 0.0
                            )
                        )
                    ),
                }
            )

        trades.sort(
            key=lambda row: row["realized_at"]
        )
        return trades, start, current

    def pnl_statement(
        self,
        *,
        period: str = "monthly",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        trades, start, current = self._closed_trades(
            period=period,
            now=now,
        )
        gross_profit = sum(
            float(row["pnl"])
            for row in trades
            if float(row["pnl"]) > 0
        )
        gross_loss = abs(
            sum(
                float(row["pnl"])
                for row in trades
                if float(row["pnl"]) < 0
            )
        )
        net_pnl = sum(
            float(row["pnl"])
            for row in trades
        )
        entry_capital = sum(
            float(row["entry_value"])
            for row in trades
        )
        wins = sum(
            1 for row in trades if float(row["pnl"]) > 0
        )
        losses = sum(
            1 for row in trades if float(row["pnl"]) < 0
        )
        breakeven = len(trades) - wins - losses

        daily: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "trade_count": 0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "net_pnl": 0.0,
                "capital_employed": 0.0,
            }
        )
        for trade in trades:
            date = str(trade["realized_at"])[:10]
            bucket = daily[date]
            bucket["trade_count"] += 1
            pnl = float(trade["pnl"])
            if pnl > 0:
                bucket["gross_profit"] += pnl
            elif pnl < 0:
                bucket["gross_loss"] += abs(pnl)
            bucket["net_pnl"] += pnl
            bucket["capital_employed"] += float(
                trade["entry_value"]
            )

        daily_rows = [
            {
                "date": date,
                "trade_count": values["trade_count"],
                "gross_profit": self._round(
                    values["gross_profit"]
                ),
                "gross_loss": self._round(
                    values["gross_loss"]
                ),
                "net_pnl": self._round(
                    values["net_pnl"]
                ),
                "capital_employed": self._round(
                    values["capital_employed"]
                ),
            }
            for date, values in sorted(daily.items())
        ]

        return {
            "scope": "paper_trading_closed_trades",
            "period": str(period).lower(),
            "period_start": (
                start.isoformat()
                if start is not None
                else None
            ),
            "period_end": current.isoformat(),
            "date_basis": (
                "closed_at_with_legacy_entry_fallback"
            ),
            "summary": {
                "trade_count": len(trades),
                "winning_trades": wins,
                "losing_trades": losses,
                "breakeven_trades": breakeven,
                "gross_profit": self._round(gross_profit),
                "gross_loss": self._round(gross_loss),
                "net_pnl": self._round(net_pnl),
                "capital_employed_sum": self._round(
                    entry_capital
                ),
                "average_capital_per_trade": (
                    self._round(entry_capital / len(trades))
                    if trades
                    else 0.0
                ),
                "average_daily_capital_employed": (
                    self._round(
                        sum(
                            float(row["capital_employed"])
                            for row in daily_rows
                        )
                        / len(daily_rows)
                    )
                    if daily_rows
                    else 0.0
                ),
                "pnl_margin_pct": (
                    round(
                        net_pnl * 100.0 / entry_capital,
                        2,
                    )
                    if entry_capital
                    else 0.0
                ),
            },
            "daily": daily_rows,
            "trades": trades,
        }

    def performance(
        self,
        *,
        period: str = "monthly",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        statement = self.pnl_statement(
            period=period,
            now=now,
        )
        trades = statement["trades"]
        summary = statement["summary"]

        wins = int(summary["winning_trades"])
        losses = int(summary["losing_trades"])
        total = int(summary["trade_count"])
        gross_profit = float(summary["gross_profit"])
        gross_loss = float(summary["gross_loss"])

        winner_values = [
            float(row["pnl"])
            for row in trades
            if float(row["pnl"]) > 0
        ]
        loser_values = [
            abs(float(row["pnl"]))
            for row in trades
            if float(row["pnl"]) < 0
        ]
        average_winner = (
            sum(winner_values) / len(winner_values)
            if winner_values
            else 0.0
        )
        average_loser = (
            sum(loser_values) / len(loser_values)
            if loser_values
            else 0.0
        )
        win_rate = (
            wins * 100.0 / total
            if total
            else 0.0
        )
        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else None
        )
        expectancy = (
            (
                wins / total * average_winner
                - losses / total * average_loser
            )
            if total
            else 0.0
        )

        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        equity_curve = []
        for trade in trades:
            equity += float(trade["pnl"])
            peak = max(peak, equity)
            drawdown = peak - equity
            max_drawdown = max(
                max_drawdown,
                drawdown,
            )
            equity_curve.append(
                {
                    "realized_at": trade["realized_at"],
                    "symbol": trade["symbol"],
                    "trade_pnl": trade["pnl"],
                    "cumulative_pnl": self._round(
                        equity
                    ),
                    "drawdown": self._round(drawdown),
                }
            )

        best = (
            max(
                trades,
                key=lambda row: float(row["pnl"]),
            )
            if trades
            else None
        )
        worst = (
            min(
                trades,
                key=lambda row: float(row["pnl"]),
            )
            if trades
            else None
        )

        return {
            "scope": statement["scope"],
            "period": statement["period"],
            "period_start": statement["period_start"],
            "period_end": statement["period_end"],
            "date_basis": statement["date_basis"],
            "summary": {
                **summary,
                "win_rate_pct": round(win_rate, 2),
                "profit_factor": (
                    round(profit_factor, 2)
                    if profit_factor is not None
                    else None
                ),
                "average_winner": self._round(
                    average_winner
                ),
                "average_loser": self._round(
                    average_loser
                ),
                "expectancy": self._round(expectancy),
                "maximum_drawdown": self._round(
                    max_drawdown
                ),
                "best_trade": best,
                "worst_trade": worst,
            },
            "equity_curve": equity_curve,
            "daily": statement["daily"],
        }

    def close(self) -> None:
        if self._owns_portfolio:
            self.portfolio_repository.close()
        if self._owns_trades:
            self.trade_repository.close()


__all__ = ["PortfolioPerformanceService"]
