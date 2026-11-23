"""The owner's compact trade columns; stock identity remains the row label."""

import math

import pandas as pd

COLUMNS = (
    "LTP",
    "OPEN PRICE",
    "CLOSE PRICE",
    "TARGET",
    "STOPLOSS",
    "EXCHANGE",
    "QTY",
    "SEGMENT",
    "REALISED P&L",
    "UNREALISED P&L",
    "BUY VALUE",
    "SELL VALUE",
)


def value(raw):
    if isinstance(raw, bool):
        return None
    try:
        result = float(raw)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def first(row, *keys):
    return next((row[key] for key in keys if row.get(key) is not None), None)


def trade_frame(rows, *, closed=False):
    output, labels = [], []
    for row in rows:
        symbol = str(row.get("symbol") or "Unknown")
        exchange = row.get("exchange") or (
            symbol.split(":", 1)[0] if ":" in symbol else "NSE"
        )
        label = symbol
        if closed:
            label += " · " + str(row.get("closed_at") or row.get("realized_at") or "")
            label += " · #" + str(row.get("id") or "")
        labels.append(label)
        output.append(
            {
                "LTP": value(first(row, "ltp", "last_price")),
                "OPEN PRICE": value(first(row, "entry_price", "average_price")),
                "CLOSE PRICE": value(row.get("exit_price")) if closed else None,
                "TARGET": value(first(row, "target", "target2")),
                "STOPLOSS": value(row.get("stoploss")),
                "EXCHANGE": exchange,
                "QTY": value(row.get("quantity")),
                "SEGMENT": row.get("segment")
                or ("EQ" if exchange in {"NSE", "BSE"} else None),
                "REALISED P&L": value(
                    row.get("realized_pnl", row.get("pnl") if closed else None)
                ),
                "UNREALISED P&L": 0.0
                if closed
                else value(first(row, "unrealized_pnl", "pnl")),
                "BUY VALUE": value(row.get("buy_value")),
                "SELL VALUE": value(row.get("sell_value")),
            }
        )
    frame = pd.DataFrame(output, columns=COLUMNS)
    frame.index = pd.Index(labels, name="Stock / trade" if closed else "Stock")
    return frame


def stock_frame(report):
    from services.conditional_stock_plan import display_plan

    plan = display_plan(report)
    targets = [value(v) for v in plan.get("targets", [])]
    target = next((v for v in targets if v is not None), None)
    quote = report.get("market_quote") or {}
    frame = trade_frame(
        [
            {
                "symbol": report["symbol"],
                "ltp": quote.get("last_price"),
                "entry_price": plan.get("entry"),
                "exit_price": target,
                "target": target,
                "stoploss": plan.get("stop_reference"),
            }
        ],
        closed=True,
    )
    frame.index = pd.Index([report["symbol"]], name="Stock")
    # Research is not a filled position: quantity, values and P&L are unknown.
    for key in ("QTY", "REALISED P&L", "UNREALISED P&L", "BUY VALUE", "SELL VALUE"):
        frame[key] = None
    return frame


def broker_frame(rows, *, holdings=False):
    mapped = []
    for row in rows:
        quantity = value(row.get("quantity"))
        average = value(row.get("average_price"))
        label = str(row.get("tradingsymbol") or row.get("symbol") or "Unknown")
        if row.get("exchange") and ":" not in label:
            label = str(row["exchange"]) + ":" + label
        if row.get("product"):
            label += " · " + str(row["product"])
        mapped.append(
            {
                "symbol": label,
                "quantity": quantity,
                "entry_price": average if quantity else None,
                "exit_price": None,
                "ltp": row.get("last_price"),
                "exchange": row.get("exchange"),
                "segment": row.get("segment"),
                "realized_pnl": row.get("realised", row.get("realized_pnl")),
                "unrealized_pnl": row.get(
                    "unrealised",
                    row.get("unrealized_pnl", row.get("pnl") if holdings else None),
                ),
                "buy_value": row.get(
                    "buy_value",
                    average * quantity
                    if holdings and average is not None and quantity is not None
                    else None,
                ),
                "sell_value": row.get("sell_value"),
            }
        )
    frame = trade_frame(mapped, closed=False)
    frame["CLOSE PRICE"] = [value(row.get("exit_price")) for row in mapped]
    return frame
