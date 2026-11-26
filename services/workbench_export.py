"""Build a consolidated workbook from recorded fills without merging accounts."""

from collections import defaultdict
from datetime import date
from math import fsum

from scanner.portfolio_policy import number
from services.research_report import excel_report


def trade_summary(fills):
    ordered = sorted(fills, key=lambda fill: fill.get("exit_at") or "")
    first, last = ordered[0], ordered[-1]
    quantities = [number(fill.get("quantity")) for fill in ordered]
    prices = [number(fill.get("exit_price")) for fill in ordered]
    net_values = [number(fill.get("net_pnl")) for fill in ordered]
    quantity = fsum(quantities) if None not in quantities else None
    net = fsum(net_values) if None not in net_values else None
    average_exit = (
        fsum(units * price for units, price in zip(quantities, prices, strict=True))
        / quantity
        if quantity and None not in prices
        else None
    )
    entry = number(first.get("entry_price"))
    stop = number(first.get("initial_stoploss"))
    initial_quantity = number(first.get("entry_quantity"))
    if initial_quantity is None:
        initial_quantity = quantity
    direction = -1 if first.get("side") in {"SHORT", "SELL"} else 1
    risk = (
        direction * (entry - stop) * initial_quantity
        if None not in (entry, stop, initial_quantity)
        and first.get("side") in {"LONG", "BUY", "SHORT", "SELL"}
        and first.get("initial_stop_basis") != "unverified_legacy_stop"
        and not any(
            isinstance(first.get(key), bool)
            for key in ("entry_price", "initial_stoploss", "entry_quantity")
        )
        and entry > 0
        and stop > 0
        and initial_quantity > 0
        and int(initial_quantity) == initial_quantity
        and direction * (entry - stop) > 0
        else None
    )
    entry_at, exit_at = first.get("entry_at"), last.get("exit_at")
    try:
        days = (
            date.fromisoformat(exit_at[:10]) - date.fromisoformat(entry_at[:10])
        ).days
    except (TypeError, ValueError):
        days = None
    return {
        "Symbol": first.get("symbol"),
        "Side": first.get("side"),
        "Entry (IST)": entry_at,
        "Final exit (IST)": exit_at,
        "Entry price": entry,
        "Weighted exit price": average_exit,
        "Quantity": quantity,
        "Net P&L (INR)": net,
        "Net R": net / risk if risk and net is not None else None,
        "Holding days": days,
    }


def consolidated_workbook(batch, accounts):
    combined, fills, dashboard, symbols = [], [], [], []
    columns = [
        "Account",
        "Trade ID",
        "Symbol",
        "Side",
        "Entry (IST)",
        "Final exit (IST)",
        "Entry price",
        "Weighted exit price",
        "Quantity",
        "Net P&L (INR)",
        "Net R",
        "Holding days",
    ]
    for account in accounts:
        account_id, report = account["batch_id"], account["report"]
        rows = report["rows"]
        trades = defaultdict(list)
        by_symbol = defaultdict(list)
        for row in rows:
            identity = row.get("trade_number") or "|".join(
                str(row.get(key) or "") for key in ("symbol", "side", "entry_at")
            )
            trades[identity].append(row)
            fills.append({"Account": account_id, **row})
        for identity, legs in trades.items():
            trade = trade_summary(legs)
            combined.append({"Account": account_id, "Trade ID": identity, **trade})
            by_symbol[trade["Symbol"]].append(trade["Net P&L (INR)"])
        for symbol, pnls in sorted(by_symbol.items(), key=lambda item: str(item[0])):
            symbols.append(
                [
                    account_id,
                    symbol,
                    len(pnls),
                    fsum(pnls) if None not in pnls else None,
                ]
            )
        metrics = report.get("metrics") or {}
        fees, slippage = (
            number(metrics.get(key))
            for key in ("transaction_costs", "slippage_impact_estimate")
        )
        net = number(metrics.get("net_profit"))
        friction = (
            fees + slippage if fees is not None and slippage is not None else None
        )
        gross = net + friction if net is not None and friction is not None else None
        alignment = report.get("history_alignment") or {}
        included = alignment.get("included_symbols")
        dashboard.append(
            [
                account_id,
                net,
                gross,
                metrics.get("return_pct"),
                metrics.get("win_rate"),
                metrics.get("profit_factor"),
                metrics.get("max_drawdown_pct"),
                friction,
                len(included) if isinstance(included, list) else None,
                account.get("requested_symbols"),
            ]
        )
    fill_columns = list(
        dict.fromkeys(["Account", *(key for row in fills for key in row)])
    )
    details = {
        "Run ID": batch["batch_id"],
        "Registry version": batch["report"].get("registry_version"),
        "SHA-256": batch["report"].get("sha256"),
    }
    for account in accounts:
        report = account["report"]
        details[account["batch_id"]] = {
            "registry_version": report.get("registry_version"),
            "sha256": report.get("sha256"),
            "parameters": report.get("parameters"),
        }
    return excel_report(
        combined,
        columns,
        details,
        kind="backtest",
        sheet_name="Combined Trades",
        extra_tables={
            "Dashboard": (
                [
                    "Account",
                    "Net P&L (INR)",
                    "Gross P&L (INR)",
                    "Net return %",
                    "Win rate %",
                    "Net profit factor",
                    "Max drawdown %",
                    "Fees and slippage (INR)",
                    "Included symbols",
                    "Requested symbols",
                ],
                dashboard,
            ),
            "Exit Fills": (
                fill_columns,
                [[row.get(key) for key in fill_columns] for row in fills],
            ),
            "Symbol Analysis": (
                ["Account", "Symbol", "Trades", "Net P&L (INR)"],
                symbols,
            ),
        },
    )
