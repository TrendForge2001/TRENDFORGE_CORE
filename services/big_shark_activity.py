"""Actual disclosed trade ingestion; no holdings inference or external requests."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from io import StringIO
from zoneinfo import ZoneInfo

from services.big_shark_portfolio import MAX_WORKBOOK_BYTES, calculate_signals

TZ = ZoneInfo("Asia/Kolkata")
TRADE_HEADERS = (
    "Trade Date",
    "Symbol",
    "Stock Name",
    "Investor Name",
    "Side",
    "Quantity",
    "Price (₹)",
    "Disclosure Time",
    "Trade ID",
)
SOURCES = ("NSE_BULK", "NSE_BLOCK", "OWNER_CSV")
MAX_RECORDS = 10000
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9&.\-]{0,24}")


def _name(value):
    return " ".join(str(value or "").split()).casefold()


def _label(value):
    value = " ".join(str(value or "").split())
    if not value or len(value) > 300:
        raise ValueError("Trade records require bounded stock and investor names.")
    return value


def timestamp(value, *, now):
    """Require an offset; a trade date or upload time is not a disclosure time."""
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Disclosure Time needs ISO date/time with timezone.") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Disclosure Time must include a timezone offset.")
    if result > now:
        raise ValueError("Disclosure Time cannot be in the future.")
    return result.astimezone(UTC).isoformat()


def _day(value):
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError("Trade Date must be a valid calendar date.")


def _amount(value, *, quantity=False):
    raw = str(value).strip().replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        raise ValueError("Actual quantity and price must be positive numbers.")
    try:
        number = Decimal(raw)
    except InvalidOperation:
        raise ValueError("Invalid numeric trade amount.") from None
    if not number.is_finite() or not 0 < number <= Decimal("1e15"):
        raise ValueError("Trade amounts must be positive and no greater than 1e15.")
    if quantity and number != number.to_integral_value():
        raise ValueError("Share quantities must be whole numbers.")
    return number


def parse_csv(data):
    if not data or len(data) > MAX_WORKBOOK_BYTES:
        raise ValueError("Upload a trade CSV of at most 2 MB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError:
        raise ValueError("Trade CSV must use UTF-8 encoding.") from None
    aliases = {
        "date": "trade_date",
        "tradedate": "trade_date",
        "symbol": "symbol",
        "securityname": "stock_name",
        "stockname": "stock_name",
        "clientname": "investor_name",
        "investorname": "investor_name",
        "buysell": "side",
        "buysellindicator": "side",
        "side": "side",
        "quantitytraded": "quantity",
        "quantity": "quantity",
        "volume": "quantity",
        "price": "price",
        "price₹": "price",
        "tradeprice": "price",
        "tradepricewghtavgprice": "price",
        "tradepriceweightedavgprice": "price",
        "tradepriceweightedaveragetradeprice": "price",
        "tradepriceweighted": "price",
        "disclosuretime": "disclosed_at",
        "disclosedat": "disclosed_at",
        "tradeid": "trade_id",
    }
    try:
        reader = csv.DictReader(StringIO(text), strict=True)
        raw_headers = reader.fieldnames or []
        mapped = [
            aliases.get(re.sub(r"[^a-z0-9₹]", "", h.casefold())) for h in raw_headers
        ]
        if len([k for k in mapped if k]) != len({k for k in mapped if k}):
            raise ValueError("Trade CSV has duplicate or ambiguous columns.")
        required = {"trade_date", "symbol", "investor_name", "side", "quantity"}
        if not required.issubset(mapped):
            raise ValueError("CSV needs date, symbol, investor, buy/sell and quantity.")
        rows = []
        for raw in reader:
            if not any(str(v or "").strip() for v in raw.values()):
                continue
            if None in raw:
                raise ValueError("CSV has extra cells; quote quantities with commas.")
            rows.append(
                {mapped[i]: raw[h] for i, h in enumerate(raw_headers) if mapped[i]}
            )
            if len(rows) > MAX_RECORDS:
                raise ValueError("Trade imports support at most 10,000 records.")
    except csv.Error:
        raise ValueError("Malformed trade CSV.") from None
    if not rows:
        raise ValueError("Trade CSV contains no records.")
    return rows


def normalise_records(records, *, now, default_disclosed_at=None):
    if not records or len(records) > MAX_RECORDS:
        raise ValueError("Supply between 1 and 10,000 actual trade records.")
    default = timestamp(default_disclosed_at, now=now)
    seen, ids, result = set(), {}, []
    duplicates = 0
    for raw in records:
        day = _day(raw.get("trade_date"))
        if day > now.astimezone(TZ).date():
            raise ValueError("Trade Date cannot be in the future.")
        symbol = str(raw.get("symbol", "")).strip().upper()
        if not SYMBOL.fullmatch(symbol) or ".." in symbol:
            raise ValueError("Trade records require an exact exchange symbol.")
        investor = _label(raw.get("investor_name"))
        stock = _label(raw.get("stock_name") or symbol)
        side = str(raw.get("side", "")).strip().upper()
        side = {"B": "BUY", "BOUGHT": "BUY", "S": "SELL", "SOLD": "SELL"}.get(
            side, side
        )
        if side not in {"BUY", "SELL"}:
            raise ValueError("Trade side must be BUY or SELL.")
        quantity = _amount(raw.get("quantity"), quantity=True)
        price = _amount(raw["price"]) if raw.get("price") not in {None, ""} else None
        disclosed = timestamp(raw.get("disclosed_at") or default, now=now)
        if disclosed and datetime.fromisoformat(disclosed).astimezone(TZ).date() < day:
            raise ValueError("Disclosure Time cannot precede Trade Date.")
        trade_id = str(raw.get("trade_id") or "").strip()
        if len(trade_id) > 100:
            raise ValueError("Trade ID is too long.")
        if price and quantity * price > Decimal("1e15"):
            raise ValueError("Reported traded value exceeds the supported limit.")
        row = {
            "trade_date": day.isoformat(),
            "symbol": symbol,
            "stock_name": stock,
            "investor_name": investor,
            "side": side,
            "quantity": int(quantity),
            "price": str(price) if price else None,
            "value_inr": str(quantity * price) if price else None,
            "disclosed_at": disclosed,
            "trade_id": trade_id or None,
        }
        identity = (
            (day.isoformat(), symbol, _name(investor), trade_id) if trade_id else None
        )
        if identity and identity in ids and ids[identity] != row:
            raise ValueError("Conflicting records share the same Trade ID.")
        if identity:
            ids[identity] = row
        key = json.dumps(
            {**row, "investor_name": _name(investor), "stock_name": symbol},
            sort_keys=True,
            ensure_ascii=False,
        )
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        result.append(row)
    return result, duplicates


def activity_view(snapshot, *, now=None):
    """Upgrade earlier private snapshots without inventing missing evidence."""
    snapshot = copy.deepcopy(snapshot)
    current = (now or datetime.now(UTC)).astimezone(TZ)
    expected = current.date()
    if current.time() < time(15, 30):
        expected -= timedelta(days=1)
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    for row in snapshot.get("signals", []):
        row.setdefault("activity_signal", row.get("signal", "NO_DATA"))
        row.setdefault("technical_confirmation", "NOT_CHECKED")
        row.setdefault("disclosure_time", None)
        row.setdefault("disclosure_time_basis", "UNKNOWN")
        row.setdefault("first_seen_at", snapshot.get("imported_at"))
        row.setdefault(
            "data_coverage",
            "OWNER_SUPPLIED_WINDOW"
            if row.get("coverage_complete")
            else "NO_TRADE_DATA"
            if not row.get("observations")
            else "PARTIAL_INPUT",
        )
        row.setdefault("technical_evidence", {})
        bar = row["technical_evidence"].get("bar_closed_at")
        if row["technical_confirmation"] in {"BUY_CONFIRMED", "SELL_EXIT_CONFIRMED"}:
            try:
                checked_bar = datetime.fromisoformat(bar).astimezone(TZ).date()
            except (ValueError, TypeError):
                checked_bar = None
            if checked_bar != expected:
                row["technical_confirmation"] = "STALE_DATA"
    return snapshot


def import_records(
    snapshot,
    records,
    *,
    source,
    metric,
    aliases=None,
    period_start=None,
    period_end=None,
    default_disclosed_at=None,
    now=None,
):
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Import clock must include a timezone.")
    if source not in SOURCES or metric not in {"quantity", "value"}:
        raise ValueError("Choose a supported trade source and quantity/value metric.")
    rows, duplicates = normalise_records(
        records, now=now, default_disclosed_at=default_disclosed_at
    )
    start = (
        _day(period_start) if period_start else min(_day(r["trade_date"]) for r in rows)
    )
    end = _day(period_end) if period_end else max(_day(r["trade_date"]) for r in rows)
    if start > end or end > now.astimezone(TZ).date():
        raise ValueError("Choose an ordered reporting window without future dates.")
    if any(not start <= _day(r["trade_date"]) <= end for r in rows):
        raise ValueError("CSV records fall outside the selected reporting window.")
    tracked = {
        _name(r[1]): str(r[1]) for r in snapshot.get("investor_rows", []) if r[1]
    }
    tracked.update(
        {_name(r[1]): str(r[1]) for r in snapshot.get("stock_rows", []) if r[1]}
    )
    names = {}
    for original, target in (aliases or {}).items():
        if (
            not isinstance(original, str)
            or not isinstance(target, str)
            or _name(target) not in tracked
        ):
            raise ValueError(
                "Each investor alias must target a tracked portfolio investor."
            )
        key = _name(original)
        if key in names and names[key] != _name(target):
            raise ValueError("Conflicting investor aliases require correction.")
        names[key] = _name(target)
    matched, unmatched = [], set()
    for row in rows:
        key = names.get(_name(row["investor_name"]), _name(row["investor_name"]))
        if key not in tracked:
            unmatched.add(row["investor_name"])
            continue
        matched.append({**row, "matched_investor": tracked[key]})
    if not matched:
        raise ValueError(
            "No tracked Big Shark investors matched. Supply verified aliases."
        )
    if metric == "value" and any(r["value_inr"] is None for r in matched):
        raise ValueError(
            "INR value comparisons require a reported price for every matched trade."
        )
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "records": rows,
                "matches": matched,
                "source": source,
                "metric": metric,
                "window": [start.isoformat(), end.isoformat()],
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    if snapshot.get("activity_import_fingerprint") == fingerprint:
        return snapshot
    result = activity_view(snapshot)
    result.pop("snapshot_id", None)
    known_names = {_name(r["stock"]): r for r in result["signals"]}
    symbol_names = {
        r["symbol"]: r["stock"] for r in result["signals"] if r.get("symbol")
    }
    group = defaultdict(list)
    for row in matched:
        label = symbol_names.get(row["symbol"])
        if label is None:
            previous = known_names.get(_name(row["stock_name"]))
            label = previous["stock"] if previous else row["stock_name"]
        if any(
            name.casefold() == label.casefold() and code != row["symbol"]
            for code, name in symbol_names.items()
        ):
            raise ValueError("A stock name maps to conflicting exchange symbols.")
        symbol_names[row["symbol"]] = label
        group[(row["symbol"], row["matched_investor"])].append(row)
    flows = []
    for (symbol, investor), trades in group.items():
        amounts = [
            sum(Decimal(str(t[key] or 0)) for t in trades if t["side"] == side)
            for key in ("quantity", "value_inr")
            for side in ("BUY", "SELL")
        ]
        if any(amount > Decimal("1e15") for amount in amounts):
            raise ValueError("Aggregated trade amount exceeds the supported limit.")
        values = [float(a) for a in amounts]
        if any(t["value_inr"] is None for t in trades):
            values[2:] = [None, None]
        flows.append(
            [
                symbol_names[symbol],
                investor,
                *values,
                start.isoformat(),
                end.isoformat(),
            ]
        )
    mappings = {r["stock"]: r["symbol"] for r in result["signals"] if r.get("symbol")}
    mappings.update({name: symbol for symbol, name in symbol_names.items()})
    signals, _ = calculate_signals(
        flows,
        mappings,
        metric=metric,
        stock_names=[r["stock"] for r in result["signals"]],
    )
    for row in signals:
        relevant = [r for r in matched if r["symbol"] == row.get("symbol")]
        times = [r["disclosed_at"] for r in relevant]
        row.update(
            {
                "activity_signal": row["signal"],
                "technical_confirmation": "NOT_CHECKED",
                "technical_evidence": {},
                "data_coverage": "DISCLOSED_ONLY"
                if relevant
                else "NO_MATCHING_DISCLOSURE",
                "coverage_complete": False,
                "reported_observations_complete": bool(relevant),
                "disclosure_time": max(times) if times and all(times) else None,
                "known_disclosure_times": sum(bool(t) for t in times),
                "disclosure_time_basis": "SOURCE_SUPPLIED_UNVERIFIED"
                if times and all(times)
                else "UNKNOWN",
                "first_seen_at": now.astimezone(UTC).isoformat(),
                "status": "Compared disclosed trades only; undisclosed trading "
                "is unknown"
                if relevant
                else "No matching disclosure in this import",
            }
        )
    result.update(
        {
            "signals": signals,
            "metric": metric,
            "trade_flow_rows": flows,
            "trade_records": matched,
            "activity_import_fingerprint": fingerprint,
            "source_sha256": fingerprint,
            "imported_at": now.astimezone(UTC).isoformat(),
            "activity_source": source,
            "activity_window": {"start": start.isoformat(), "end": end.isoformat()},
            "activity_import": {
                "matched_records": len(matched),
                "unmatched_records": len(rows) - len(matched),
                "unmatched_investors": sorted(unmatched),
                "duplicate_records_ignored": duplicates,
            },
            "refresh_status": "uploaded_trade_disclosures_not_a_live_feed",
            "counts": {
                s: sum(r["signal"] == s for r in signals)
                for s in ("BUY", "SELL", "HOLD", "NO_DATA")
            },
            "execution_enabled": False,
        }
    )
    return result


def trade_template_bytes():
    output = StringIO()
    csv.writer(output).writerow(TRADE_HEADERS)
    return output.getvalue().encode("utf-8-sig")
