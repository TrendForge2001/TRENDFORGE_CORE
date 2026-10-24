"""Scanner selection and independent multi-stock historical simulations."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd
import streamlit as st

from scanner.technical_strategy import strategy_profile
from webapp.api_client import ApiError
from webapp.paper_excel import safe_csv_bytes
from webapp.ui import render_api_error

BATCH_KEY = "tf_scanner_backtest_batch"


def scanner_description(mode: str) -> dict:
    """Describe the actual canonical scanner/backtest profile, without new rules."""
    profile = strategy_profile(mode)
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
        if not isinstance(row, dict) or row.get("signal") not in {
            "BUY",
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
    if not selected or len(selected) > 100:
        raise ValueError("Select 1–100 scanner stocks")
    profile = scanner_description(scan["mode"])
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
                    "run_id": f"scanner-bt-{batch['batch_id']}-{index}",
                },
                timeout=240,
            )
            validate_backtest(result)
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
    return rows + batch["errors"]


def render_scanner_backtests(client, *, mode: str, authorized: bool) -> None:
    profile = scanner_description(mode)
    left, right = st.columns([1, 2], gap="large")
    with left, st.container(border=True):
        st.subheader("Discover scanners")
        st.markdown(f"**{profile['scanner']}**")
        st.caption(f"{mode.title()} · {profile['interval']} · NSE equities · Long only")
        st.caption("Select the timeframe above to change scanner type.")
        with st.expander("View conditions and indicators", expanded=True):
            st.write(profile["indicators"])
            for condition in profile["conditions"]:
                st.write("• " + condition)
        with st.form(f"scanner_backtest_scan_{mode}"):
            universe = st.text_area(
                "Scanner universe (NSE symbols)", "RELIANCE\nTCS\nSBIN"
            )
            scan_period = st.selectbox(
                "Scan history",
                strategy_profile(mode).allowed_periods,
                index=1 if mode == "swing" else 2,
            )
            scan_clicked = st.form_submit_button("Scan stocks", disabled=not authorized)
        if scan_clicked:
            st.session_state.pop("tf_r726_scan_result", None)
            symbols = list(
                dict.fromkeys(
                    s.strip().upper()
                    for s in universe.replace(",", "\n").splitlines()
                    if s.strip()
                )
            )
            if not 1 <= len(symbols) <= 100:
                st.error("Enter 1–100 NSE symbols.")
            else:
                try:
                    snapshot = client.post_json(
                        "/technical/scan",
                        {
                            "symbols": symbols,
                            "mode": mode,
                            "period": scan_period,
                            "top_n": 100,
                            "execute_paper": False,
                            "run_id": f"backtest-scan-{uuid4().hex}",
                        },
                        timeout=240,
                    )
                    if (
                        snapshot.get("status") != "completed"
                        or snapshot.get("mode") != mode
                        or not isinstance(snapshot.get("results"), list)
                    ):
                        raise ApiError(
                            "The backend returned an invalid scanner snapshot"
                        )
                    st.session_state["tf_r726_scan_result"] = {
                        **snapshot,
                        "observed_at": datetime.now(UTC).isoformat(),
                    }
                except ApiError as exc:
                    render_api_error(exc, title="Scanner unavailable")
    with right:
        st.subheader("Scanner results → Backtest")
        st.caption(
            "Uses the latest Technical Scanner result from this session, "
            "or scan stocks here."
        )
        snapshot = st.session_state.get("tf_r726_scan_result", {})
        signal = st.selectbox("Signal filter", ["BUY", "HOLD", "EXIT", "All signals"])
        minimum = st.slider("Minimum scanner score", 0, 100, 0)
        matches = matching_rows(snapshot, mode, signal, minimum)
        if snapshot.get("mode") and snapshot.get("mode") != mode:
            st.info(
                "The saved scan belongs to another timeframe. "
                "Run this scanner to refresh it."
            )
        if matches:
            st.caption(
                f"Scan {snapshot.get('run_id', '—')} · "
                f"{snapshot.get('period', '—')} · {len(matches)} matches"
            )
            st.dataframe(
                pd.DataFrame(matches)[
                    [
                        "symbol",
                        "signal",
                        "score",
                        *(["bar_at"] if "bar_at" in matches[0] else []),
                    ]
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No stocks match. Run a scan or change the signal/score filter.")
        st.warning(
            "Stocks are selected using the latest scan, then tested over historical "
            "data. This selection can bias results; it is not a point-in-time "
            "universe backtest."
        )
        with st.form(f"scanner_stock_batch_{mode}"):
            options = [row["symbol"] for row in matches]
            selected = st.multiselect("Stocks to backtest", options, default=options)
            period = st.selectbox(
                "Backtest history",
                strategy_profile(mode).allowed_periods,
                index=1 if mode == "swing" else 2,
            )
            capital = st.number_input(
                "Capital per stock (₹)", min_value=1000.0, max_value=1e9, value=100000.0
            )
            cost = st.number_input(
                "Cost (basis points per side)",
                min_value=0.0,
                max_value=1000.0,
                value=12.0,
            )
            slip = st.number_input(
                "Slippage (basis points per side)",
                min_value=0.0,
                max_value=1000.0,
                value=5.0,
            )
            st.caption(
                "Independent simulations with equal capital per stock. "
                "Requests run sequentially and may take several minutes."
            )
            run = st.form_submit_button(
                "Backtest selected stocks",
                type="primary",
                disabled=not authorized or not options,
            )
        if run:
            st.session_state.pop(BATCH_KEY, None)
            if not selected or not set(selected).issubset(options):
                st.error("Select at least one stock from the current scanner matches.")
            else:
                bar = st.progress(0.0, text="Running independent stock backtests…")
                st.session_state[BATCH_KEY] = run_stock_batch(
                    client,
                    selected,
                    scan={
                        **snapshot,
                        "selection_filter": {
                            "signal": signal,
                            "minimum_score": minimum,
                        },
                    },
                    settings={
                        "period": period,
                        "capital": float(capital),
                        "cost_bps": float(cost),
                        "slippage_bps": float(slip),
                    },
                    progress=bar.progress,
                )
        if not authorized:
            st.info("The Admin API Key is required to scan and backtest.")
    batch = st.session_state.get(BATCH_KEY)
    if not batch:
        return
    st.divider()
    st.subheader("Multi-stock backtest comparison")
    st.caption(
        f"Saved result · {batch['scanner']['scanner']} · "
        f"{batch['settings']['period']} · {batch['created_at']}"
    )
    a, b, c = st.columns(3)
    a.metric("Requested stocks", len(batch["results"]) + len(batch["errors"]))
    b.metric("Completed", len(batch["results"]))
    c.metric("Failed", len(batch["errors"]))
    frame = pd.DataFrame(comparison_rows(batch))
    st.dataframe(frame, hide_index=True, use_container_width=True)
    st.download_button(
        "Export stock comparison (CSV)",
        safe_csv_bytes(frame),
        "trendforge_stock_backtests.csv",
        "text/csv",
    )
    trades = [
        {**trade, "symbol": result["symbol"], "scanner": batch["scanner"]["scanner"]}
        for result in batch["results"]
        for trade in result["trades"]
    ]
    if trades:
        st.download_button(
            "Export all stock trades (CSV)",
            safe_csv_bytes(pd.DataFrame(trades)),
            "trendforge_stock_trades.csv",
            "text/csv",
        )
    if batch["results"]:
        chosen = st.selectbox(
            "Inspect stock result", [r["symbol"] for r in batch["results"]]
        )
        detail = next(r for r in batch["results"] if r["symbol"] == chosen)
        st.dataframe(
            pd.DataFrame(detail["trades"]), hide_index=True, use_container_width=True
        )
        curve = detail.get("equity_curve")
        if curve:
            st.caption("Stock equity curve")
            equity = pd.DataFrame(curve)
            if {"date", "equity"}.issubset(equity.columns):
                st.line_chart(equity.set_index("date")[["equity"]])
            else:
                st.dataframe(equity, hide_index=True, use_container_width=True)
    with st.expander("Batch settings and scanner evidence"):
        st.json({key: value for key, value in batch.items() if key not in {"results"}})
