"""Owner-scoped public refresh. This module never imports a trading executor."""

import copy
import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta

from database.repositories.big_shark_repository import BigSharkSnapshotConflict
from providers.big_shark_public import BigSharkPublicProvider, PublicFeedError
from services.big_shark_activity import TZ, _name, import_records
from services.big_shark_portfolio import RULE, calculate_signals

REFRESH_LOCK = threading.Lock()
VERSION = "big-shark-public-feeds-v1"


def _tracked(snapshot, aliases):
    names = {
        _name(row[1]): str(row[1])
        for row in (*snapshot.get("investor_rows", []), *snapshot.get("stock_rows", []))
        if len(row) > 1 and row[1]
    }
    verified = {}
    for source, target in aliases.items():
        if _name(target) not in names:
            raise ValueError("Each verified alias must target a tracked investor.")
        key = _name(source)
        if key in verified and verified[key] != _name(target):
            raise ValueError("Conflicting verified investor aliases.")
        verified[key] = _name(target)
    return names, verified


def _bootstrap(public, *, now, metric):
    stocks = [
        [
            r["stock_name"],
            r["investor_name"],
            r["reported_action"],
            r["holding_percent"],
            r["reported_change"],
            r["holding_value_cr"],
            r["quantity_held"],
        ]
        for r in public["rows"]
    ]
    signals, _ = calculate_signals(
        [], metric=metric, stock_names=[r[0] for r in stocks]
    )
    return {
        "rule": RULE,
        "metric": metric,
        "stock_rows": stocks,
        "investor_rows": [
            [
                r["category"],
                r["investor_name"],
                r.get("company_holdings"),
                r.get("networth_cr"),
                r["url"],
            ]
            for r in public["investors"]
        ],
        "signals": signals,
        "trade_flow_rows": [],
        "source_sha256": public["document_sha256"],
        "reporting_period": public["reporting_period"],
        "period_verified": False,
        "source_urls": [public["source_url"]],
        "imported_at": now.isoformat(),
        "refresh_status": "public_holdings_only_actual_trades_required",
        "portfolio_origin": "MONEYCONTROL_PUBLIC",
        "execution_enabled": False,
        "counts": {
            s: sum(r["signal"] == s for r in signals)
            for s in ("BUY", "SELL", "HOLD", "NO_DATA")
        },
    }


def _no_disclosures(snapshot, *, source, start, end, now):
    result = copy.deepcopy(snapshot)
    result.pop("snapshot_id", None)
    symbols = {r["stock"]: r["symbol"] for r in result["signals"] if r.get("symbol")}
    signals, _ = calculate_signals(
        [],
        symbols,
        metric=result["metric"],
        stock_names=[r["stock"] for r in result["signals"]],
    )
    for row in signals:
        row.update(
            activity_signal="NO_DATA",
            technical_confirmation="NOT_CHECKED",
            technical_evidence={},
            data_coverage="NO_MATCHING_DISCLOSURE",
            coverage_complete=False,
            disclosure_time=None,
            disclosure_time_basis="UNKNOWN",
            first_seen_at=now.isoformat(),
        )
    result.update(
        signals=signals,
        trade_flow_rows=[],
        trade_records=[],
        activity_source=source,
        activity_window={"start": start.isoformat(), "end": end.isoformat()},
        activity_import={"matched_records": 0},
        imported_at=now.isoformat(),
        counts={
            s: sum(r["signal"] == s for r in signals)
            for s in ("BUY", "SELL", "HOLD", "NO_DATA")
        },
        execution_enabled=False,
        refresh_status="no_matching_public_disclosures",
    )
    result["source_sha256"] = hashlib.sha256(
        json.dumps(
            [
                source,
                start.isoformat(),
                end.isoformat(),
                sorted(symbols.items()),
                "no_disclosures",
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    result["activity_import_fingerprint"] = result["source_sha256"]
    return result


def refresh_public_sources(
    repo,
    *,
    provider=None,
    now=None,
    source="NSE_BULK",
    start=None,
    end=None,
    metric="quantity",
    aliases=None,
    expected_snapshot_id=None,
):
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Refresh clock requires a timezone.")
    today = now.astimezone(TZ).date()
    end = end or today
    start = start or end - timedelta(days=6)
    if source not in {"NSE_BULK", "NSE_BLOCK"} or metric not in {"quantity", "value"}:
        raise ValueError("Choose NSE bulk or block deals and a quantity/value metric.")
    if not start <= end <= today or (end - start).days > 30:
        raise ValueError("Choose an ordered past window of at most 31 days.")
    if not REFRESH_LOCK.acquire(blocking=False):
        raise PublicFeedError("REFRESH_ALREADY_RUNNING")
    try:
        original = repo.latest()
        if expected_snapshot_id and (
            not original or original["snapshot_id"] != expected_snapshot_id
        ):
            raise BigSharkSnapshotConflict(
                "Portfolio changed; reload before refreshing."
            )
        aliases = aliases or {}
        if original:
            _tracked(original, aliases)
        provider = provider or BigSharkPublicProvider()
        previous = repo.source_state() or {}
        state = {
            **previous,
            "version": VERSION,
            "checked_at": now.isoformat(),
            "paper_orders_allowed": False,
            "broker_orders_allowed": False,
        }
        failures = {}
        public = None
        try:
            public = provider.holdings(now=now)
        except PublicFeedError as exc:
            failures["MONEYCONTROL"] = exc.code
        if original is None:
            if public is None:
                state.update(status="unavailable", failures=failures)
                repo.save_source_state(state)
                return state
            base = _bootstrap(public, now=now, metric=metric)
        else:
            base = copy.deepcopy(original)
        tracked, verified = _tracked(base, aliases)
        if public is not None:
            previous_rows = {
                json.dumps(
                    {k: v for k, v in r.items() if k != "first_seen_at"}, sort_keys=True
                ): r
                for r in previous.get("holdings", {}).get("rows", [])
            }
            rows = []
            for row in public["rows"]:
                key = verified.get(
                    _name(row["investor_name"]), _name(row["investor_name"])
                )
                if key in tracked:
                    matched_row = {**row, "portfolio_investor": tracked[key]}
                    identity = json.dumps(matched_row, sort_keys=True)
                    first_seen = previous_rows.get(identity, {}).get(
                        "first_seen_at", now.isoformat()
                    )
                    rows.append({**matched_row, "first_seen_at": first_seen})
            state["holdings"] = {
                **public,
                "rows": rows,
                "fetched_at": now.isoformat(),
                "public_rows": len(public["rows"]),
                "matched_rows": len(rows),
            }
        try:
            trade_feed = provider.trades(source=source, start=start, end=end, now=now)
            rows = trade_feed["rows"]
            matching = [
                r
                for r in rows
                if verified.get(_name(r["investor_name"]), _name(r["investor_name"]))
                in tracked
            ]
            actual_start, actual_end = start, end
            if trade_feed["coverage"] == "SINGLE_DAILY_REPORT" and rows:
                from datetime import date

                days = [date.fromisoformat(r["trade_date"]) for r in rows]
                actual_start, actual_end = min(days), max(days)
            if matching:
                updated = import_records(
                    base,
                    rows,
                    source=source,
                    metric=metric,
                    aliases=aliases,
                    period_start=actual_start,
                    period_end=actual_end,
                    now=now,
                )
            else:
                base["metric"] = metric
                updated = _no_disclosures(
                    base, source=source, start=actual_start, end=actual_end, now=now
                )
            state["trades"] = {k: v for k, v in trade_feed.items() if k != "rows"}
            state["trades"].update(
                fetched_at=now.isoformat(),
                records_received=len(rows),
                matched_records=len(matching),
                requested_start=start.isoformat(),
                requested_end=end.isoformat(),
                actual_start=actual_start.isoformat(),
                actual_end=actual_end.isoformat(),
                unmatched_records=len(rows) - len(matching),
                unmatched_investors=sorted(
                    {
                        r["investor_name"]
                        for r in rows
                        if verified.get(
                            _name(r["investor_name"]), _name(r["investor_name"])
                        )
                        not in tracked
                    }
                )[:100],
            )
        except ValueError as exc:
            failures[source] = getattr(exc, "code", "SOURCE_RECORDS_INVALID")
            updated = base
        # Ownership/import changes during the public requests must win.
        saved = repo.save(
            updated,
            expected_snapshot_id=original["snapshot_id"] if original else None,
            expected_absent=original is None,
        )
        state.update(
            status="unavailable"
            if len(failures) == 2
            else "partial"
            if failures
            else "refreshed",
            failures=failures,
            snapshot_id=saved["snapshot_id"],
            last_success_at=now.isoformat()
            if public is not None or source not in failures
            else previous.get("last_success_at"),
        )
        repo.save_source_state(state)
        return state
    finally:
        REFRESH_LOCK.release()


def source_view(repo):
    state = repo.source_state() or {"status": "not_refreshed", "version": VERSION}
    config = repo.source_state("config") or {
        "enabled": False,
        "source": "NSE_BULK",
        "metric": "quantity",
        "aliases": {},
    }
    return {
        **state,
        "config": config,
        "paper_orders_allowed": False,
        "broker_orders_allowed": False,
    }
