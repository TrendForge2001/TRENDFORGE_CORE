"""Reconciled entry/exit fills; scanner evidence cannot become a trade report."""

from __future__ import annotations

import math
from collections import defaultdict

import pandas as pd

from scanner.portfolio_policy import (
    ACCOUNT_CAPITAL,
    CASH_RESERVE,
    DEPLOYMENT_LIMIT,
    MAX_POSITIONS,
    number,
)
from webapp.trade_timestamps import market_timestamp


class ReportValidationError(ValueError):
    """Invalid numerical or fill evidence; messages contain no provider data."""


TRADE_COLUMNS = [
    "trade_number",
    "symbol",
    "side",
    "entry_at",
    "entry_price",
    "entry_quantity",
    "exit_at",
    "exit_price",
    "quantity",
    "exit_reason",
    "transaction_costs",
    "net_pnl",
]


def _close(left, right, tolerance=0.02):
    a, b = number(left), number(right)
    return a is not None and b is not None and abs(a - b) <= tolerance


def _key(row):
    return row.get("symbol"), row.get("side"), market_timestamp(row.get("entry_at"))


def _fill_valid(fill):
    entry, exit_at = (
        market_timestamp(fill.get("entry_at")),
        market_timestamp(fill.get("exit_at")),
    )
    entry_price, exit_price = (
        number(fill.get("entry_price")),
        number(fill.get("exit_price")),
    )
    cost, pnl = number(fill.get("transaction_costs")), number(fill.get("net_pnl"))
    qty = fill.get("quantity")
    if (
        not isinstance(fill.get("symbol"), str)
        or not fill["symbol"]
        or not isinstance(fill.get("side"), str)
        or fill["side"] not in {"LONG", "SHORT"}
        or type(qty) is not int
        or qty <= 0
        or entry is None
        or exit_at is None
        or exit_at < entry
        or entry_price is None
        or entry_price <= 0
        or exit_price is None
        or exit_price <= 0
        or cost is None
        or cost < 0
        or pnl is None
    ):
        return False
    direction = -1 if fill["side"] == "SHORT" else 1
    gross = direction * (exit_price - entry_price) * qty
    return _close(gross - cost, pnl)


def validate_result(result: dict, *, historical=False) -> None:
    if not isinstance(result, dict):
        raise ReportValidationError("Invalid historical trade result")
    metrics, policy = result.get("metrics"), result.get("parameters")
    trades, curve = result.get("trades"), result.get("equity_curve")
    capital, deployment, reserve, slots = (
        ACCOUNT_CAPITAL,
        DEPLOYMENT_LIMIT,
        CASH_RESERVE,
        MAX_POSITIONS,
    )
    if historical and isinstance(metrics, dict) and isinstance(policy, dict):
        capital, deployment, reserve = (
            number(value)
            for value in (
                metrics.get("initial_capital"),
                policy.get("deployment_limit"),
                policy.get("cash_reserve"),
            )
        )
        slots = policy.get("max_positions")
        if (
            capital is None
            or capital <= 0
            or deployment is None
            or not 0 < deployment <= capital
            or reserve is None
            or not 0 <= reserve < capital
            or type(slots) is not int
            or not 1 <= slots <= MAX_POSITIONS
        ):
            raise ReportValidationError("Historical account policy is incomplete")
    if (
        result.get("status") != "completed"
        or not isinstance(metrics, dict)
        or not isinstance(policy, dict)
        or not isinstance(trades, list)
        or not all(isinstance(row, dict) for row in trades)
        or not isinstance(curve, list)
        or not curve
        or metrics.get("initial_capital") != capital
        or policy.get("deployment_limit") != deployment
        or policy.get("cash_reserve") != reserve
        or policy.get("max_positions") != slots
    ):
        raise ReportValidationError(
            "Rerun the backtest using the full-capital, zero-reserve policy"
        )
    final, net = number(metrics.get("final_capital")), number(metrics.get("net_profit"))
    pnls = [number(row.get("net_pnl")) for row in trades]
    if (
        final is None
        or net is None
        or not _close(final - net, capital)
        or None in pnls
        or type(metrics.get("total_trades")) is not int
        or metrics["total_trades"] != len(trades)
        or not _close(math.fsum(pnls), net, 0.02 + len(trades) * 0.01)
        or any(
            number(metrics.get(key)) is None
            for key in ("return_pct", "max_drawdown_pct")
        )
    ):
        raise ReportValidationError("Portfolio trade P&L does not reconcile")
    if any(
        not isinstance(trade.get("symbol"), str)
        or not trade["symbol"]
        or not isinstance(trade.get("side"), str)
        or trade["side"] not in {"LONG", "SHORT"}
        or market_timestamp(trade.get("entry_at")) is None
        or market_timestamp(trade.get("exit_at")) is None
        for trade in trades
    ):
        raise ReportValidationError("Portfolio entry/exit evidence is incomplete")
    keys = [_key(trade) for trade in trades]
    if len(keys) != len(set(keys)):
        raise ReportValidationError(
            "Duplicate historical positions in the trade report"
        )
    fills = result.get("exit_fills")
    if fills is not None:
        if not isinstance(fills, list) or not all(
            isinstance(fill, dict) and _fill_valid(fill) for fill in fills
        ):
            raise ReportValidationError("Historical exit-fill accounting is incomplete")
        grouped = defaultdict(list)
        for fill in fills:
            grouped[_key(fill)].append(fill)
        if set(grouped) != set(keys):
            raise ReportValidationError("Exit fills do not match completed positions")
        for trade in trades:
            legs = grouped[_key(trade)]
            qty = trade.get("quantity")
            if (
                type(qty) is not int
                or qty <= 0
                or market_timestamp(trade.get("exit_at")) is None
                or sum(leg["quantity"] for leg in legs) != qty
                or any(
                    not _close(leg["entry_price"], trade.get("entry_price"), 1e-8)
                    for leg in legs
                )
                or any(
                    market_timestamp(leg["exit_at"])
                    > market_timestamp(trade.get("exit_at"))
                    for leg in legs
                )
                or not _close(
                    math.fsum(leg["net_pnl"] for leg in legs), trade.get("net_pnl")
                )
                or not _close(
                    math.fsum(leg["transaction_costs"] for leg in legs),
                    trade.get("transaction_costs"),
                )
            ):
                raise ReportValidationError(
                    "Partial-exit quantities or P&L do not reconcile"
                )
    elif not all(_fill_valid(trade) for trade in trades):
        raise ReportValidationError("Portfolio entry/exit evidence is incomplete")
    for point in curve:
        if not isinstance(point, dict):
            raise ReportValidationError("Invalid portfolio equity observations")
        cash, equity, deployed = (
            number(point.get(key)) for key in ("cash", "equity", "capital_committed")
        )
        count = point.get("open_positions")
        if (
            cash is None
            or cash < -1e-6
            or equity is None
            or market_timestamp(point.get("date")) is None
            or deployed is None
            or not -1e-6 <= deployed <= deployment + 1e-6
            or type(count) is not int
            or not 0 <= count <= slots
        ):
            raise ReportValidationError("Portfolio capital limits do not reconcile")
    if not _close(curve[-1]["equity"], final):
        raise ReportValidationError("Portfolio equity does not reconcile")


def trade_report(result: dict, *, historical=False) -> pd.DataFrame:
    validate_result(result, historical=historical)
    rows = []
    positions = {
        _key(trade): (index, trade) for index, trade in enumerate(result["trades"], 1)
    }
    for fill in result.get("exit_fills", result["trades"]):
        index, position = positions[_key(fill)]
        rows.append(
            {
                **{key: fill.get(key) for key in TRADE_COLUMNS},
                "trade_number": index,
                "entry_quantity": position["quantity"],
            }
        )
    frame = pd.DataFrame(rows, columns=TRADE_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["trade_number", "exit_at"], kind="stable"
        ).reset_index(drop=True)
    return frame
