"""Opt-in, consumed-once operator verification of a full official stock list."""

import json
import logging
import os
import re

from scanner.weekly_floor import STRATEGY_ID

LOG = logging.getLogger(__name__)


def official_symbols(stock_list):
    from providers.nse_broad_market_constituents import (
        NSEBroadMarketConstituentProvider,
    )

    payload = NSEBroadMarketConstituentProvider().load(stock_list)
    symbols = list(dict.fromkeys(row["symbol"] for row in payload["members"]))
    if len(symbols) < {"NIFTY 50": 50, "NIFTY 200": 200, "NIFTY 500": 500}[stock_list]:
        raise ValueError("Incomplete official universe")
    LOG.warning(
        "research_campaign_membership index=%s stocks=%s source=%s stale=%s",
        stock_list,
        len(symbols),
        payload.get("source"),
        bool(payload.get("stale")),
    )
    return symbols


def request_research_campaign(app):
    raw = os.getenv("TRENDFORGE_RESEARCH_CAMPAIGN", "")
    if not raw or os.getenv("RENDER_SERVICE_ID") != "srv-db1tb7jncjis73c994e0":
        return None
    try:
        if len(raw) > 2048:
            raise ValueError
        intent = json.loads(raw)
        selected = "backtest" in intent
        required = {"request_id", "stock_list", "period"}
        if set(intent) != (required | {"backtest"} if selected else required):
            raise ValueError
        request_id = intent["request_id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
            raise ValueError
        allowed = (
            {"NIFTY 50", "NIFTY 200", "NIFTY 500"}
            if selected
            else {"NIFTY 200", "NIFTY 500"}
        )
        if intent["stock_list"] not in allowed or intent["period"] not in {"2y", "5y"}:
            raise ValueError
        manager = app.state.research_manager_getter()
        db = manager.repository.db
        db.execute(
            "CREATE TABLE IF NOT EXISTS research_campaigns (request_id TEXT "
            "PRIMARY KEY, stock_list TEXT NOT NULL, "
            "scan_batch TEXT, backtest_batch TEXT)"
        )
        claim = db.execute(
            "INSERT OR IGNORE INTO research_campaigns (request_id,stock_list) "
            "VALUES (?,?)",
            (request_id, intent["stock_list"]),
        )
        if not claim.rowcount:
            LOG.warning(
                "research_campaign request=%s status=already_consumed", request_id
            )
            return None
        request = {
            "symbols": official_symbols(intent["stock_list"]),
            "strategy_id": STRATEGY_ID,
            "horizon": "long_term",
            "stock_list": intent["stock_list"],
            "period": intent["period"],
        }
        ids = []
        for kind in ("backtest",) if selected else ("scan", "backtest"):
            if selected:
                from api.research_reports_router import ResearchRequest

                overrides = intent["backtest"]
                allowed_fields = {
                    "strategy_id",
                    "horizon",
                    "initial_capital",
                    "risk_fraction",
                    "max_positions",
                    "cost_bps",
                    "slippage_bps",
                    "move_stop_after_partial",
                }
                if (
                    not isinstance(overrides, dict)
                    or not {"strategy_id", "horizon"}
                    <= overrides.keys()
                    <= allowed_fields
                ):
                    raise ValueError("Invalid backtest configuration")
                configured = ResearchRequest.model_validate({**request, **overrides})
                batch = app.state.submit_research_batch(kind, configured)
            else:
                batch = manager.submit(kind, request)
            batch_id = batch["batch_id"]
            ids.append(batch_id)
            field = "scan_batch" if kind == "scan" else "backtest_batch"
            db.execute(
                f"UPDATE research_campaigns SET {field}=? WHERE request_id=?",
                (batch_id, request_id),
            )
            LOG.warning(
                "research_campaign request=%s kind=%s batch=%s stocks=%s "
                "status=submitted orders_submitted=0",
                request_id,
                kind,
                batch_id,
                len(request["symbols"]),
            )

            def finished(_future, batch_id=batch_id, kind=kind):
                saved = manager.repository.get(batch_id)
                report = saved.get("report") or {}
                LOG.warning(
                    "research_campaign_result request=%s kind=%s batch=%s status=%s "
                    "code=%s rows=%s coverage=%s variants=%s sha256=%s "
                    "diagnostic=%s orders_submitted=0",
                    request_id,
                    kind,
                    batch_id,
                    saved["status"],
                    saved.get("error_code"),
                    len(report.get("rows", [])),
                    len(report.get("history_alignment", {}).get("coverage", [])),
                    len(report.get("comparisons", [])),
                    report.get("sha256"),
                    json.dumps(saved.get("diagnostic"), sort_keys=True),
                )

            manager.futures[batch_id].add_done_callback(finished)
        return ids
    except Exception as error:
        from services.research_failure import failure_diagnostic

        LOG.warning(
            "research_campaign status=not_submitted diagnostic=%s orders_submitted=0",
            json.dumps(failure_diagnostic(error), sort_keys=True),
        )
        return None
