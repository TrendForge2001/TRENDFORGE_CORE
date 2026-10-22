"""Export the canonical daily paper P&L statement and trade books to an Excel workbook."""
from __future__ import annotations

from io import BytesIO

import pandas as pd


def paper_daily_xlsx(statement: dict, portfolio: dict) -> bytes:
    """Generate three sheets; realized P&L comes from the authoritative /pnl endpoint."""
    if statement.get("scope") != "paper_trading_closed_trades" or statement.get("period") != "daily":
        raise ValueError("Expected canonical daily paper-trading P&L statement")
    summary = statement.get("summary") or {}
    daily = statement.get("daily") or []
    closed = statement.get("trades") or []
    opened = portfolio.get("positions") or []
    if not all(isinstance(rows, list) for rows in (daily, closed, opened)):
        raise ValueError("Invalid P&L/trade ledger response")
    summary_rows = [
        ["Metric", "Value"],
        ["Statement period", "Daily (Asia/Kolkata)"],
        ["Period end", str(statement.get("period_end") or "")],
        ["Closed trades", int(summary.get("trade_count") or 0)],
        ["Realized profit (₹)", float(summary.get("gross_profit") or 0)],
        ["Realized loss (₹)", float(summary.get("gross_loss") or 0)],
        ["Realized net P&L (₹)", float(summary.get("net_pnl") or 0)],
        ["Open positions", int(portfolio.get("open_positions") or 0)],
        ["Open unrealized P&L (₹)", float(portfolio.get("unrealized_pnl") or 0)],
        ["Accounting note", "Open unrealized P&L is a current mark, NOT intraday movement."],
        ["Date basis", str(statement.get("date_basis") or "")],
    ]
    buf = BytesIO()
    with pd.ExcelWriter(
        buf, engine="xlsxwriter",
        engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}},
    ) as writer:
        tables = {
            "Daily P&L": pd.DataFrame(summary_rows[1:], columns=summary_rows[0]),
            "Daily Closed Trades": pd.DataFrame(closed),
            "Open Paper Portfolio": pd.DataFrame(opened),
            "Daily Aggregates": pd.DataFrame(daily),
        }
        for name, frame in tables.items():
            if frame.empty and not len(frame.columns):
                frame = pd.DataFrame({"No records": []})
            frame.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            sheet.freeze_panes(1, 0)
            sheet.autofilter(0, 0, max(1, len(frame)), len(frame.columns) - 1)
            header = writer.book.add_format({"bold": True, "bg_color": "#102E44", "font_color": "#FFFFFF", "border": 0})
            for index, column in enumerate(frame.columns):
                sheet.write(0, index, str(column), header)
                sheet.set_column(index, index, min(34, max(16, len(str(column)) + 3)))
    return buf.getvalue()
