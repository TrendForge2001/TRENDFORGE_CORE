"""Scanner selection and independent multi-stock historical simulations."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import uuid4

from scanner.technical_strategy import strategy_profile
from scanner.workspace_strategies import validate_workspace_strategy
from webapp.api_client import ApiError

BATCH_KEY = "tf_scanner_backtest_batch"


def scanner_description(mode: str, strategy_id: str | None = None) -> dict:
    """Describe the actual canonical scanner/backtest profile, without new rules."""
    profile = strategy_profile(mode)
    registered = validate_workspace_strategy(mode, strategy_id)
    if registered:
        return {
            "scanner": registered["name"],
            "mode": mode,
            "strategy_id": strategy_id,
            "interval": profile.interval,
            "indicators": ", ".join(registered["indicators"]),
            "conditions": [
                "All entry checks must pass. "
                "Stock score = percentage of checks passed.",
                *registered["entry_rules"],
                *registered["stoploss_rules"],
                *registered["target_rules"],
                *registered["exit_rules"],
                *registered["notes"],
            ],
        }
    intraday = profile.mode == "intraday"
    return {
        "scanner": f"Technical {profile.mode.title()} Momentum",
        "mode": profile.mode,
        "interval": profile.interval,
        "indicators": ("EMA 9/20/50, VWAP" if intraday else "EMA 20/50/100")
        + ", VWMA 9/26, RSI, MACD, ADX / DI, RVOL, ATR, breakout",
        "conditions": [
            f"Weighted technical score ≥ {profile.entry_score:g} "
            "plus a fresh entry trigger",
            "EMA 9 crosses above EMA 20 or fresh breakout"
            if intraday
            else "EMA 20 crosses above EMA 50, fresh breakout, or EMA 20 reclaim",
            f"Score inputs: RSI {profile.rsi_min:g}–{profile.rsi_max:g}, "
            f"ADX ≥ {profile.adx_min:g}, +DI > −DI, RVOL ≥ {profile.rvol_min:g}",
            "Trend, VWMA, MACD and price-reference checks "
            "contribute to the weighted score",
            f"ATR stop reference {profile.stop_atr:g}×; "
            f"reward/risk reference {profile.reward_risk:g}×",
            "Exit on trend/reference reversal, RSI < 50, "
            "bearish MACD, or low technical score",
        ],
    }


def matching_rows(snapshot: dict, mode: str, signal: str, minimum: float) -> list[dict]:
    """Never mix another profile's snapshot or include failed symbols."""
    if snapshot.get("status") != "completed" or snapshot.get("mode") != mode:
        return []
    rows = []
    seen = set()
    raw_rows = snapshot.get("results")
    if not isinstance(raw_rows, list):
        return []
    for row in raw_rows:
        if isinstance(row, dict) and row.get("signal") == "HOLD":
            row = {**row, "signal": "WAIT"}
        if not isinstance(row, dict) or row.get("signal") not in {
            "BUY",
            "SELL",
            "WAIT",
            "HOLD",
            "EXIT",
        }:
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        try:
            score = float(row.get("score"))
        except (ValueError, TypeError):
            continue
        if (
            not symbol
            or symbol in seen
            or not math.isfinite(score)
            or score < minimum
            or (signal != "All signals" and row["signal"] != signal)
        ):
            continue
        rows.append({**row, "symbol": symbol})
        seen.add(symbol)
    return rows


def validate_backtest(result: dict) -> None:
    if (
        result.get("status") != "completed"
        or not isinstance(result.get("metrics"), dict)
        or not isinstance(result.get("trades"), list)
        or not all(isinstance(row, dict) for row in result["trades"])
    ):
        raise ApiError("The backend returned an invalid historical backtest result")


def run_stock_batch(
    client, symbols: list[str], *, scan: dict, settings: dict, progress=None
) -> dict:
    """Use existing admin-protected simulation API sequentially; isolate failures."""
    selected = list(dict.fromkeys(symbols))
    if not selected or len(selected) > 1000:
        raise ValueError("Select 1–1000 scanner stocks")
    profile = scanner_description(scan["mode"], scan.get("strategy_id"))
    valid_rows = matching_rows(scan, scan["mode"], "All signals", 0)
    if not set(selected).issubset({row["symbol"] for row in valid_rows}):
        raise ValueError(
            "Selected stocks must belong to the completed scanner snapshot"
        )
    batch = {
        "batch_id": uuid4().hex,
        "created_at": datetime.now(UTC).isoformat(),
        "scanner": profile,
        "scan_run_id": scan.get("run_id"),
        "universe": scan.get("universe"),
        "scan_period": scan.get("period"),
        "scan_observed_at": scan.get("observed_at"),
        "selection_filter": scan.get("selection_filter"),
        "selection": [
            {k: row.get(k) for k in ("symbol", "signal", "score", "bar_at")}
            for row in valid_rows
            if row.get("symbol") in selected
        ],
        "settings": dict(settings),
        "results": [],
        "errors": [],
    }
    for index, symbol in enumerate(selected):
        try:
            result = client.post_json(
                "/technical/backtest",
                {
                    **settings,
                    "symbol": symbol,
                    "mode": scan["mode"],
                    "strategy_id": scan.get("strategy_id"),
                    "run_id": f"scanner-bt-{batch['batch_id']}-{index}",
                },
                timeout=240,
            )
            validate_backtest(result)
            if result.get("strategy_id") != scan.get("strategy_id"):
                raise ApiError("Backtest result strategy did not match the scanner")
            if result.get("symbol", symbol) != symbol:
                raise ApiError("Backtest result did not match the requested symbol")
            batch["results"].append({**result, "symbol": symbol})
        except ApiError as exc:
            # Fixed summary only; upstream errors may contain account/transport data.
            batch["errors"].append(
                {
                    "symbol": symbol,
                    "status": "failed",
                    "error": "Historical backtest unavailable",
                    "http_status": exc.status_code,
                }
            )
        if progress:
            progress((index + 1) / len(selected))
    return batch


def comparison_rows(batch: dict) -> list[dict]:
    rows = []
    for result in batch["results"]:
        metrics = result["metrics"]
        rows.append(
            {
                "symbol": result["symbol"],
                "status": "completed",
                "scanner": batch["scanner"]["scanner"],
                "score": next(
                    (
                        row["score"]
                        for row in batch["selection"]
                        if row["symbol"] == result["symbol"]
                    ),
                    None,
                ),
                "interval": batch["scanner"]["interval"],
                "indicators": batch["scanner"]["indicators"],
                **{
                    name: metrics.get(name)
                    for name in (
                        "total_trades",
                        "net_profit",
                        "return_pct",
                        "win_rate",
                        "max_drawdown_pct",
                        "profit_factor",
                        "initial_capital",
                        "final_capital",
                    )
                },
            }
        )
    scores = {row["symbol"]: row.get("score") for row in batch["selection"]}
    return rows + [
        {**row, "score": scores.get(row["symbol"])} for row in batch["errors"]
    ]


def render_scanner_backtests(client, *, mode: str, authorized: bool) -> None:
    """Keep legacy callers on the same approved weekly research controls."""
    from webapp.research_workspace import render_research_workspace

    render_research_workspace(
        client, authorized=authorized, key="legacy_weekly_backtest", backtest=True
    )
