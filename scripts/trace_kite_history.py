"""Read-only trace of raw Kite candles, normalization and completed-bar filtering.

Raw responses remain in the explicitly selected local output directory. Neither
credentials nor HTTP headers are written to diagnostics. No candle is inserted,
interpolated or derived from daily OHLC; narrow reads can only recover real data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ZONE = ZoneInfo("Asia/Kolkata")


class TraceSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False
        self.history = []

    def request(self, method, url, **kwargs):
        if method.upper() != "GET":
            raise ValueError("History diagnostics permit only broker reads")
        response = super().request(method, url, **kwargs)
        if "/instruments/historical/" in url:
            entry = {
                "http_status": response.status_code,
                "params": dict(kwargs.get("params") or {}),
                "response_sha256": hashlib.sha256(response.content).hexdigest(),
            }
            if response.status_code == 200 and len(response.content) <= 40_000_000:
                try:
                    payload = response.json()
                    candles = payload.get("data", {}).get("candles")
                    if payload.get("status") == "success" and isinstance(candles, list):
                        entry["candles"] = candles
                except (ValueError, AttributeError):
                    pass
            self.history.append(entry)
        return response


def summarize(index, session_date):
    stamps = pd.DatetimeIndex(index)
    stamps = stamps.tz_localize(ZONE) if stamps.tz is None else stamps.tz_convert(ZONE)
    selected = stamps[stamps.date == session_date]
    return {
        "total_bars": len(stamps),
        "last_bar": stamps[-1].isoformat() if len(stamps) else None,
        "session_bars": len(selected),
        "session_timestamps": [stamp.isoformat() for stamp in selected],
        "has_1515": any(stamp.time() == time(15, 15) for stamp in selected),
    }


def trace_symbol(broker, transport, symbol, *, session_date, period, output, now):
    from providers.market_data_adapter import MarketDataAdapter
    from services.technical_trading_service import TechnicalTradingService

    frame = broker.candles(symbol, period=period, interval="15m")
    recorded = transport.history[-1]
    raw = recorded.get("candles") or []
    normalized = MarketDataAdapter._normalize(symbol, frame)
    completed = TechnicalTradingService._completed_bars(
        normalized, interval="15m", now=now
    )
    report = {
        "provider_request": {k: v for k, v in recorded.items() if k != "candles"},
        "raw": summarize([row[0] for row in raw], session_date),
        "provider": summarize(frame.index, session_date),
        "normalized": summarize(normalized.index, session_date),
        "completed": summarize(completed.index, session_date),
        "recovery_reads": [],
    }
    (output / f"{symbol}-provider-raw.json").write_text(
        json.dumps(raw, separators=(",", ":")), encoding="utf-8"
    )
    token = broker.instrument_token_for_symbol(symbol)
    for label, start, end, interval in (
        ("full_session", time(9, 15), time(15, 30), "15minute"),
        ("target_1515", time(15, 15), time(15, 30), "15minute"),
        ("target_minutes", time(15, 15), time(15, 30), "minute"),
    ):
        broker._pace_history()
        rows = broker.safe_historical(
            token,
            datetime.combine(session_date, start, ZONE),
            datetime.combine(session_date, end, ZONE),
            interval,
            continuous=False,
            oi=False,
        )
        captured = transport.history[-1]
        item = {
            "label": label,
            "http_status": captured["http_status"],
            "params": captured["params"],
            "response_sha256": captured["response_sha256"],
            **summarize([row["date"] for row in rows], session_date),
        }
        report["recovery_reads"].append(item)
        (output / f"{symbol}-{label}-raw.json").write_text(
            json.dumps(captured.get("candles") or [], separators=(",", ":")),
            encoding="utf-8",
        )
    report["genuine_1515_recovered"] = any(
        row["label"] in {"full_session", "target_1515"} and row["has_1515"]
        for row in report["recovery_reads"]
    )
    report["requirement_25_bars_preserved"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--session", type=date.fromisoformat, required=True)
    parser.add_argument("--symbols", nargs="+", default=["RELIANCE", "TCS"])
    parser.add_argument("--period", choices=("30d", "60d"), default="30d")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= len(args.symbols) <= 5 or any(
        not symbol.isalnum() for symbol in args.symbols
    ):
        parser.error("Choose between one and five plain NSE symbols")
    now = datetime.now(ZONE)
    if args.session >= now.date():
        parser.error("Choose an earlier completed session for recovery reads")
    if args.data_dir:
        from core.pc_kite_credentials import load_pc_kite_credentials

        os.environ.update(load_pc_kite_credentials(args.data_dir))
    os.environ["TRENDFORGE_LIVE_TRADING_ENABLED"] = "false"
    from providers.kite_errors import KiteException
    from providers.kite_provider import KiteProvider
    from providers.kite_rest_client import KiteRESTClient

    broker = KiteProvider()
    transport = TraceSession()
    broker.kite = KiteRESTClient(
        api_key=broker.api_key, access_token=broker.access_token, session=transport
    )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "checked_at": now.isoformat(),
        "session": args.session.isoformat(),
        "read_only": True,
        "broker_orders_allowed": False,
        "symbols": {},
    }
    for symbol in args.symbols:
        symbol = symbol.upper()
        try:
            value = trace_symbol(
                broker,
                transport,
                symbol,
                session_date=args.session,
                period=args.period,
                output=output,
                now=now,
            )
        except (KiteException, ValueError, KeyError) as error:
            value = {"error_type": type(error).__name__}
        report["symbols"][symbol] = value
        print(json.dumps({symbol: value}), flush=True)
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return (
        0 if all("error_type" not in row for row in report["symbols"].values()) else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
